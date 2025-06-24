from packaging.version import Version
from ldpc import __version__ as ldpc_version
print("Using LDPC version v{}".format(ldpc_version))

from ldpc import BpDecoder  
from ldpc.bplsd_decoder import BpLsdDecoder
from ldpc import BpOsdDecoder  

import numpy as np
import time

from scipy import sparse 
from dem_to_matrices import detector_error_model_to_check_matrices
from IBM_STIM import create_bivariate_bicycle_codes, build_circuit, select_configuration


""" 
! Flujo de trabajo

El orquerstador lee los argumentos de las cola SQS e invoca al worker pasando la información mediante eventos.
El worker lee la información del evento e inicia su ejecucion.

Informacion dentro del evento:
    - codeConfig: Código a probar
    - p: tasa de error física a simular 
    - NMCs_batch: rango de Monte Carlo trials de este worker
    - decoder_type: tipo de decodificador (BP, BPLSD, BPOSD)
    - arguments: argumentos para el decodificador BP
    TODO: - ID: Identificador de argumentos, codeConfig, p y numero de lote que se usará para juntarlos posteriormente.
    Se genera en args_mixer.py y se añade a la cola SQS junto con los argumentos. En orchestrator.py se concatena con codeConfig y p y eso forma el ID que se recibe en el worker.

    ? EJEMPLO de evento
    event = {
        "codeConfig": "72",
        "p": 0.001,
        "NMCs_batch": 500,
        "decoder_type": "BPOSD",
        "arguments": { "max_iter":100, "bp_method":"product_sum", "schedule":"parallel", "osd_method":"osd_0"}
        "ID": 123456789_72_001 
    }
"""

def lambda_handler(event, context=None):

    time_start = time.time()

    # Debug variables
    show_prints = False
    show_times = True

    # Event variables received from Lambda Orchestrator
    codeConfig = event["codeConfig"]
    p = event["p"]
    NMCs_batch = event["NMCs_batch"]
    decoder_type = event["decoder_type"]
    arguments = event["arguments"]

    # * Build quantum code
    # Parameters for simulation
    config = select_configuration(codeConfig)
    ell, m = config["ell"], config["m"]
    a1, a2, a3 = config["a"]
    b1, b2, b3 = config["b"]
    d = config["d"]

    # Construct the polynomials A and B for the code
    A_x_pows, A_y_pows = [a1], [a2, a3] 
    B_x_pows, B_y_pows = [b2, b3], [b1]
    code, A_list, B_list = create_bivariate_bicycle_codes(ell, m, A_x_pows, A_y_pows, B_x_pows, B_y_pows)

    # * Build circuit and detector error model
    circuit = build_circuit(code, A_list, B_list, p=p, num_repeat=d, z_basis=False, use_both=False)
    dem = circuit.detector_error_model()
    
    # * Convert detector error model to check matrices
    matrices = detector_error_model_to_check_matrices(dem, allow_undecomposed_hyperedges=True)
    pcm = matrices.check_matrix                     # Parity check matrix
    observable_mat = matrices.observables_matrix    # Logical observables matrix
    if arguments.get("error_channel") == "dem_error_channel":
        arguments["error_channel"] = matrices.priors     # Prior error probabilities for each channel 

    # * Initialize decoders
    if decoder_type == "BP":
        _decoder = BpDecoder(pcm, error_rate=float(p), **event["arguments"])
    elif decoder_type == "BPLSD":
        _decoder = BpLsdDecoder(pcm, error_rate=float(p), **event["arguments"])
    elif decoder_type == "BPOSD":
        _decoder = BpOsdDecoder(pcm, error_rate=float(p), **event["arguments"])
    else:
        raise ValueError(f"Decoder type {decoder_type} not supported")

    # * Initialize results
    Pl = 0
    time_av = 0
    time_max = 0
    
    # * Run Monte Carlo trials
    for _ in range(NMCs_batch):
        # ! ¿Es necesario compilar el circuito cada iteración?
        sampler = circuit.compile_detector_sampler()
        detectors, observables = sampler.sample(1, separate_observables=True)
        
        a = time.time()
        predicted_observables = _decoder.decode(detectors[0])
        b = time.time()
        time_av += (b - a) / NMCs_batch

        time_max = max(time_max, (b - a))

        logical_error = (observable_mat @ predicted_observables + observables) % 2

        if np.any(logical_error):
            Pl += 1 / NMCs_batch

    # * Print results
    if show_times:
        print("Execution time:", time.time() - time_start)

    # * Results
    results = {
        "codeConfig": codeConfig,
        "p": p,
        "NMCs_batch": NMCs_batch,
        "decoder_type": decoder_type,
        "arguments": arguments,
        f"Pl{decoder_type}": Pl,
        f"time_av_{decoder_type}": time_av,
        f"time_max_{decoder_type}": time_max
    }

    # TODO: Guardar los resultados en una dynamoDB


    for k, v in results.items():
        print(f"{k}: {v}")
    print("--------------------------------")
    



if __name__ == "__main__":
    # * For local testing
    
    # BP
    # ? BpDecoder(pcm, max_iter=100, error_rate=float(p), bp_method="product_sum", error_channel=dem_error_channel)
    lambda_handler({
        "codeConfig": 72,
        "p": 0.001,
        "NMCs_batch": 500,
        "decoder_type": "BP",
        "arguments": { "max_iter":100, "bp_method":"product_sum", "error_channel":"dem_error_channel"}
    })

    # BPLSD
    # ? BpLsdDecoder(pcm, max_iter=100, error_rate=float(p), bp_method="product_sum", osd_method = 'lsd_cs', osd_order = 2)
    lambda_handler({
        "codeConfig": 72,
        "p": 0.001,
        "NMCs_batch": 500,
        "decoder_type": "BPLSD",
        "arguments": { "max_iter":100, "bp_method":"product_sum", "osd_method":"lsd_cs", "osd_order":2}
    })

    # BPOSD
    # ? BpOsdDecoder(pcm, max_iter=100, error_rate=float(p), bp_method="product_sum", schedule = 'parallel', osd_method="osd_0")
    lambda_handler({
        "codeConfig": 72,
        "p": 0.001,
        "NMCs_batch": 500,
        "decoder_type": "BPOSD",
        "arguments": { "max_iter":100, "bp_method":"product_sum", "schedule":"parallel", "osd_method":"osd_0"}
    })
