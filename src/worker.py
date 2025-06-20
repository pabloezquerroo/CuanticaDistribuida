def lambda_handler(event, context=None):
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


    # Time check
    time_start = time.time()
    print("Starting time:", time_start)

    # Debug variables
    show_prints = False
    show_times = True

    # Event variables received from Lambda Orchestrator
    """
    Leemos variables pasados por evento de Lambda
        - codeConfig: Código a probar
        - NMCs_range: rango de Monte Carlo trials de este worker
        - p: tasa de error física a simular 
        ? Argumentos de BpDecoder, BpLsdDecoder y BpOsdDecoder ->
    """
    codeConfig = event["codeConfig"]
    p = event["p"]
    NMCs_range = event["NMCs_range"]
    decoder_name = event["decoder_name"]

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
    dem_error_channel = matrices.priors             # Prior error probabilities for each channel

    # !     Los argumentos de BpDecoder, BpLsdDecoder y BpOsdDecoder seran recibidos por eventos ->
    # !     El orquestador será quien lea los args de la cola SQS y los envíe.
    # TODO:     Evaluar si es conveniente que este script se ejecute una vez por cada decoder, ->
    # TODO:     o si es mejor que se ejecute una vez y se lean los parámetros de cada decoder
    _bp = BpDecoder(pcm, max_iter=100, error_rate=float(p), bp_method="product_sum", error_channel=dem_error_channel)
    _bplsd = BpLsdDecoder(pcm, max_iter=100, error_rate=float(p), bp_method="product_sum", osd_method='lsd_cs', osd_order=2)
    _bposd = BpOsdDecoder(pcm, max_iter=100, error_rate=float(p), bp_method="product_sum", schedule='parallel', osd_method="osd_0")


    # TODO: Guardado de los resultados
    
    PlBP = PlBPLSD = PlBPOSD = 0
    time_av_BP = time_av_BPLSD = time_av_BPOSD = 0
    time_max_BP = time_max_BPLSD = time_max_BPOSD = 0

    
    for _ in range(NMCs_range):
        # ? Es necesario compilar el circuito cada vez?
        sampler = circuit.compile_detector_sampler()
        detectors, observables = sampler.sample(1, separate_observables=True)

        # BP
        a = time.time()
        pred_bp = _bp.decode(detectors[0])
        b = time.time()
        time_av_BP += (b - a) / (NMCs_range)
        time_max_BP = max(time_max_BP, b - a)

        # BPLSD
        a = time.time()
        pred_lsd = _bplsd.decode(detectors[0])
        b = time.time()
        time_av_BPLSD += (b - a) / (NMCs_range)
        time_max_BPLSD = max(time_max_BPLSD, b - a)

        # BPOSD
        a = time.time()
        pred_osd = _bposd.decode(detectors[0])
        b = time.time()
        time_av_BPOSD += (b - a) / (NMCs_range)
        time_max_BPOSD = max(time_max_BPOSD, b - a)

        # Logical error
        err_bp = (observable_mat @ pred_bp + observables) % 2
        err_lsd = (observable_mat @ pred_lsd + observables) % 2
        err_osd = (observable_mat @ pred_osd + observables) % 2

        if np.any(err_bp): PlBP += 1 / (NMCs_range)
        if np.any(err_lsd): PlBPLSD += 1 / (NMCs_range)
        if np.any(err_osd): PlBPOSD += 1 / (NMCs_range)

    return {
        "PlBP": PlBP,
        "PlBPLSD": PlBPLSD,
        "PlBPOSD": PlBPOSD,
        "time_av_BP": time_av_BP,
        "time_max_BP": time_max_BP,
        "time_av_BPLSD": time_av_BPLSD,
        "time_max_BPLSD": time_max_BPLSD,
        "time_av_BPOSD": time_av_BPOSD,
        "time_max_BPOSD": time_max_BPOSD,
    }
