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

El orquerstador lee los argumentos de las colas SQS e invoca al worker pasando la información mediante eventos.
El worker lee la información del evento e inicia su ejecucion.

Informacion dentro del evento:
    - codeConfig: Código a probar
    - p: tasa de error física a simular 
    - NMCs_range: rango de Monte Carlo trials de este worker
    - BP_arguments: argumentos para el decodificador BP
    - BPLSD_arguments: argumentos para el decodificador BPLSD
    - BPOSD_arguments: argumentos para el decodificador BPOSD

    ? Probablemente haga falta recibir un id_args para identificar el conjunto de argumentos y juntar los lotes posteriormente.

    ? EJEMPLO de evento
    event = {
        "codeConfig": "72",
        "p": 0.001,
        "NMCs_range": 500,
        "BP_arguments":  {"bp_method":"product_sum", "error_channel":"dem_error_channel"},
        "BPLSD_arguments": {"bp_method":"product_sum", "osd_method":"lsd_cs", "osd_order":2},
        "BPOSD_arguments": {"bp_method":"product_sum", "schedule":"parallel", "osd_method":"osd_0"}
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
    NMCs_range = event["NMCs_range"]
    BP_arguments = event.get("BP_arguments", {})
    BPLSD_arguments = event.get("BPLSD_arguments", {})
    BPOSD_arguments = event.get("BPOSD_arguments", {})

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

    if BP_arguments.get("error_channel") == "dem_error_channel":
        BP_arguments["error_channel"] = matrices.priors     # Prior error probabilities for each channel 

    # * Initialize decoders
    _bp = BpDecoder(pcm, max_iter=100, error_rate=float(p), **event["BP_arguments"])
    _bplsd = BpLsdDecoder(pcm, max_iter=100, error_rate=float(p), **event["BPLSD_arguments"])
    _bposd = BpOsdDecoder(pcm, max_iter=100, error_rate=float(p), **event["BPOSD_arguments"])

    # * Initialize variables for results
    PlBP = PlBPLSD = PlBPOSD = 0
    time_av_BP = time_av_BPLSD = time_av_BPOSD = 0
    time_max_BP = time_max_BPLSD = time_max_BPOSD = 0

    
    for _ in range(NMCs_range):
        # ! ¿Es necesario compilar el circuito cada iteración?
        sampler = circuit.compile_detector_sampler()
        detectors, observables = sampler.sample(1, separate_observables=True)

        # BP
        a = time.time()
        predicted_observables = _bp.decode(detectors[0])
        b = time.time()
        time_av_BP += (b - a) / NMCs_range

        # BPLSD
        a = time.time()
        predicted_observables_lsd = _bplsd.decode(detectors[0])
        b = time.time()
        time_av_BPLSD += (b - a) / NMCs_range

        # BPOSD
        a = time.time()
        predicted_observables_osd = _bposd.decode(detectors[0])
        b = time.time()
        time_av_BPOSD += (b - a) / NMCs_range

        # Logical error
        logical_error_bp = (observable_mat @ predicted_observables + observables) % 2
        logical_error_lsd = (observable_mat @ predicted_observables_lsd + observables) % 2
        logical_error_osd = (observable_mat @ predicted_observables_osd + observables) % 2

        if np.any(logical_error_bp): PlBP += 1 / NMCs_range
        if np.any(logical_error_lsd): PlBPLSD += 1 / NMCs_range
        if np.any(logical_error_osd): PlBPOSD += 1 / NMCs_range

    if show_times:
        print("Execution time:", time.time() - time_start)
    
    # TODO: "id_args": id_args -> recibido desde el orquestador para identificar el conjunto de argumentos y juntar los lotes posteriormente.
    results = {
        "codeConfig": codeConfig,
        "p": p,
        "BP_arguments": BP_arguments,
        "BPLSD_arguments": BPLSD_arguments,
        "BPOSD_arguments": BPOSD_arguments,
        "PlBP": PlBP,
        "PlBPLSD": PlBPLSD,
        "PlBPOSD": PlBPOSD,
        "time_av_BP": time_av_BP,
        "time_max_BP": time_max_BP,
        "time_av_BPLSD": time_av_BPLSD,
        "time_max_BPLSD": time_max_BPLSD,
        "time_av_BPOSD": time_av_BPOSD,
        "time_max_BPOSD": time_max_BPOSD
    }

    print("Results:")
    for k, v in results.items():
        print(f"{k}: {v}")

    # TODO: Guardar los resultados en una dynamoDB


if __name__ == "__main__":
    # For local testing
    lambda_handler({
        "codeConfig": "72",
        "p": 0.001,
        "NMCs_range": 500,
        "BP_arguments": {"bp_method": "product_sum", "error_channel": "dem_error_channel"},
        "BPLSD_arguments": {"bp_method": "product_sum", "osd_method": "lsd_cs", "osd_order": 2},
        "BPOSD_arguments": {"bp_method": "product_sum", "schedule": "parallel", "osd_method": "osd_0"}
    })
    