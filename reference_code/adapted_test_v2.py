from packaging.version import Version
from ldpc import __version__ as ldpc_version

# Check if the installed LDPC library version is 2.0.0 or higher
ldpc_v2 = Version(ldpc_version) >= Version("2.0.0")

# Print the version of the LDPC library and whether it is v2 or not
print("Using LDPC version v{}".format(ldpc_version))
print("ldpc_v2: ", ldpc_v2)

# Conditional imports based on the LDPC version
if ldpc_v2 is True:
    from ldpc import BpDecoder  
    from ldpc.bplsd_decoder import BpLsdDecoder
    from ldpc import BpOsdDecoder  
else:
    from ldpc import bp_decoder  
    from ldpc import bposd_decoder  

import numpy as np  
import time  
from scipy import sparse 
from dem_to_matrices import detector_error_model_to_check_matrices
import boto3
from botocore.exceptions import ClientError
import logging
import os
import io
import pickle

from IBM_STIM import create_bivariate_bicycle_codes, build_circuit, select_configuration, save_sparse_matrices

import dotenv

# Cargar variables de entorno desde el archivo .env
dotenv.load_dotenv()

automorphism=True

def get_connection_s3():
    """Create and return a Boto3 S3 client.

    The configuration (endpoint_url, aws_access_key_id, aws_secret_access_key)
    is loaded from environment variables. These are necessary for providers like
    Backblaze. For AWS, many of these are configured automatically when running
    in an AWS environment.

    Returns:
        boto3.Client: An S3 client object.
    """
    return boto3.client(
        's3',
        endpoint_url=os.getenv('S3_ENDPOINT_URL'),
        region_name=os.getenv('AWS_DEFAULT_REGION'),
        aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
        aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY')
    )

def get_automorphism_from_s3(auto_id, error_rate):
    """
    Download a specific automorphism from S3
    """
    s3 = get_connection_s3()
    error_rate_str = f"{error_rate:.6f}".rstrip('0').rstrip('.')
    
    automorphism_path = os.getenv('S3_AUTOMORPHISMS_PATH')
    s3_path = f"{automorphism_path}{error_rate_str}/auto_{auto_id}/data.pkl"
    logging.info(f"Downloading automorphism from S3: {s3_path}")
    buffer = io.BytesIO()
    try:
        s3.download_fileobj(
            os.getenv('S3_BUCKET_NAME'),
            s3_path,
            buffer
        )
        buffer.seek(0)
        data = pickle.load(buffer)

        # ! DEBUG: Pintar tipos de datos
        # logging.info(f"Type of data['ensemble']: {type(data['ensemble'])}, length: {len(data['ensemble'])}")
        # logging.info(f"Type of data['priors']: {type(data['priors'])}, length: {len(data['priors'])}")
        # logging.info(f"Type of data['row_perm']: {type(data['row_perm'])}, length: {len(data['row_perm'])}")
        # logging.info(f"PCM (ensemble) shape: {data['ensemble'].shape}")
        # logging.info(f"Priors shape: {data['priors'].shape}")
        # logging.info(f"Row_perm shape: {data['row_perm'].shape}")

        return data['ensemble'], data['priors'], data['row_perm']
    except ClientError as e:
        logging.error(f"Error downloading automorphism {auto_id}: {str(e)}")
        return None, None, None

# * STARTING TIME
time_start = time.time()
print("Starting time:", time_start)

# * DEBUG VARIABLE
show_prints = False
show_times = False
successful_correction_patterns = [] # ! DEBUG

# * PARAMETERS FOR SIMULATION
# Codes to test
codesConfig = [72, 90, 108, 144, 288, 784]
codeConfig = codesConfig[3]  # Select one of the codes to test

# Number of Monte Carlo trials per physical error rate
# NMCs = [10**6, 10**6, 10**6, 10**6, 10**6]  
NMCs = [1000]

# Physical error rates to simulate (between 0.1% and 0.5%)
# ps = np.linspace(0.001, 0.005, num=5) # ? Para empezar debemos probar solo con 0.001
ps = [0.003]
print("Physical error rates to simulate:", ps)

# * DICTIONARIES FOR RESULTS
# Logical error rates for decoders
PlsBP, PlsBPLSD, PlsBPOSD = {}, {}, {}
PlsBP[codeConfig] = []
PlsBPLSD[codeConfig] = []
PlsBPOSD[codeConfig] = []

# Execution times for decoders
times_BP, times_BPLSD, times_BPOSD = {}, {}, {}
times_BP[codeConfig] = []
times_BPLSD[codeConfig] = []
times_BPOSD[codeConfig] = []


# * BUILD QUANTUM LDPC CODE
# Select the configuration for the code
config = select_configuration(codeConfig)
ell, m = config["ell"], config["m"]
a1, a2, a3 = config["a"]
b1, b2, b3 = config["b"]
d = config["d"]
 
# Construct the polynomials A and B for the code
A_x_pows, A_y_pows = [a1], [a2, a3] 
B_x_pows, B_y_pows = [b2, b3], [b1]

# Create the bivariate bicycle code
code, A_list, B_list = create_bivariate_bicycle_codes(
    config["ell"], config["m"],
    A_x_pows, A_y_pows, B_x_pows, B_y_pows)
pcm = sparse.csc_matrix(code.hx, dtype=np.uint8)

if show_times:
    pcm_time = time.time() - time_start
    print("Time to create the code and parity check matrix:", pcm_time)

# * ITERATING OVER THE PHYSICAL ERROR RATES
for index, p in enumerate(ps):
    if show_prints:
        print(f"Running simulation for physical error rate: {p}")


    circuit = build_circuit(code, A_list, B_list, 
                        p=p, # physical error rate
                        num_repeat=config["d"], # usually set to code distance
                        z_basis=True,   # whether in the z-basis or x-basis
                        use_both=False, # whether use measurement results in both basis to decode one basis
                        )
    
    dem = circuit.detector_error_model()

    # Proofs adapting the STIM to BP using as reference
    # https://github.com/oscarhiggott/stimbposd/blob/main/src/stimbposd/bp_osd.py 
    hx_shape = code.hx.shape  # Shape of the X parity matrix
    hz_shape = code.hz.shape  # Shape of the Z parity matrix
    matrices = detector_error_model_to_check_matrices(dem, allow_undecomposed_hyperedges=True)  # Converts the error model to useful matrices
    num_detectors = dem.num_detectors  # Number of detectors in the model
    num_errors = dem.num_errors        # Number of possible errors in the model
    h_shape = matrices.check_matrix.shape  # Shape of the check (parity) matrix
    dem_error_channel = matrices.priors        # Prior error probabilities for each channel 
    pcm = matrices.check_matrix            # Parity check matrix
    observable_mat = matrices.observables_matrix  # Logical observables matrix
    if show_prints:
        print("hx_shape: ", hx_shape)
        print("hz_shape: ", hz_shape)
        print("Number of detectors: ", num_detectors)
        print("Number of errors: ", num_errors)
        print("h_shape: ", h_shape)
        print("channel_probs= ", dem_error_channel)
        print("channel_probs is of size: ", dem_error_channel.shape)
        print("pcm is of size: ", pcm.shape)

    if show_times:
        time_circuit_dem_matrices = time.time() - time_start
        print("Time to create the circuit, detector error model and matrices:", time_circuit_dem_matrices)

    
    # * PARAMETERS FOR AUTOMORPHISMS
    if automorphism:
        pcm, dem_error_channel, row_perm = get_automorphism_from_s3(0, error_rate=p)


    # ! DEGUG: Comparar elementos
    # dem_error_channel con matrices.priors, viendo las diferencias
    # for i in range(len(dem_error_channel)):
    #     if dem_error_channel[i] != matrices.priors[i]:
    #         print(f"Difference at index {i}: dem_error_channel={dem_error_channel[i]}, matrices.priors={matrices.priors[i]}")
    # ! DEBUG: Guardar datos de automorfismos
    # Guardar datos en archivo local para comparación
    # data_to_save = {
    #     'pcm': pcm,
    #     'dem_error_channel': dem_error_channel,
    #     'row_perm': row_perm
    # }
    # np.savetxt("../experiments/dem_error_channel.txt", dem_error_channel)
    # np.savetxt("../experiments/dem_error_channel_example.txt", matrices.priors)
    # Crear nombre de archivo con la configuración actual
    # filename = f"py_data_config_{codeConfig}_p_{p:.6f}.pkl"
    # filepath = os.path.join(os.getcwd(), "../experiments", filename)
    # with open(filepath, 'wb') as f:
    #     pickle.dump(data_to_save, f)    
    # print(f"Datos guardados en ../experiments/")
    # exit()
    # ! DEBUG: Fin guardar datos de automorfismos

    # https://software.roffe.eu/ldpc/quantum_decoder.html               
    _bp = BpDecoder(pcm, max_iter=100, ms_scaling_factor=0.9, error_rate=float(p), bp_method="minimum_sum", error_channel=dem_error_channel) # error_channel antes era channel_probs
    # _bp = BpDecoder(pcm, max_iter=100, error_rate=float(p), bp_method="product_sum", error_channel=dem_error_channel) #  error_channel antes era channel_probs
    _bplsd = BpLsdDecoder(pcm, max_iter=100, error_rate=float(p), bp_method="product_sum", osd_method = 'lsd_cs', osd_order = 2)
    _bposd = BpOsdDecoder(pcm, max_iter=100, error_rate=float(p), bp_method="product_sum", schedule = 'parallel', osd_method="osd_0")


    # Initialize variables for tracking performance
    PlBP, PlBPLSD, PlBPOSD = 0, 0, 0
    time_av_BP, time_max_BP = 0, 0
    time_av_BPOSD, time_max_BPOSD = 0, 0
    time_av_BPLSD, time_max_BPLSD = 0, 0
    
    if show_times:
        time_before_monte_carlo = time.time() - time_start
        print("Time until beginning of the Monte Carlo patterns:", time_before_monte_carlo)

    for pattern in range(NMCs[index]):
        
        if show_prints:
            time_init_pattern = time.time() - time_start
            print(f"pattern {pattern + 1}/{NMCs[index]} for physical error rate {p} (time since start: {time_init_pattern} seconds)")

        # Generate aleatory samples of simulated errors
        sampler = circuit.compile_detector_sampler(seed=42 + pattern + 1)  # Seed for reproducibility
        num_shots = 1
        detectors, observables = sampler.sample(num_shots, separate_observables=True)

        if show_times and pattern % 1000 == 0:
            time_detectors_observables = time.time() - time_start
            print("Time to sample detectors and observables:", time_detectors_observables)
            
        #BP
        a = time.time()  
        if automorphism:
            transformed_detectors = (row_perm @ detectors[0] % 2) # Automorphism
            predicted_error = _bp.decode(transformed_detectors)

        else:
            predicted_error = _bp.decode(detectors[0])

        if show_times and pattern % 1000 == 0:
            time_bp_decoding = time.time() - time_start
            print("Time for BP decoding (pattern % 1000 == 0):", time_bp_decoding)

        #soft_decisions = _bp.bp_decoding
        #convergence = _bp.converge
        #pattern_stop = _bp.iter
        #soft_decisions_llr =  _bp.log_prob_ratios
        #print(soft_decisions_llr)
        b = time.time() 
        time_av_BP += (b - a) / NMCs[index]  
        if show_prints:
            print("time_av_BP:",time_av_BP)
        times_BP[codeConfig].append(b-a)
        if show_prints:
            print("times_BP:",times_BP)
        time_max_BP = max(time_max_BP, (b - a))  
        if show_prints:
            print("time_max_BP:",time_max_BP)
            print("\n")    
        if show_prints:
            print("predicted error:\n")
            print(predicted_error)
     
        '''
        #BPLSD    
        a = time.time()
        predicted_error_lsd = _bplsd.decode(detectors[0])

        if show_times and pattern % 1000 == 0:
            time_bplsd_decoding = time.time() - time_start
            print("Time for BPLSD decoding (pattern % 1000 == 0):", time_bplsd_decoding)

        b = time.time()
        time_av_BPLSD += (b - a) / NMCs[index]
        if show_prints:
            print("time_av_BPOSD:",time_av_BPLSD)
        times_BPLSD[codeConfig].append(b-a)
        if show_prints:
            print("times_BPLSD:",times_BPLSD)
        time_max_BPLSD = max(time_max_BPLSD, (b - a))  
        if show_prints:
            print("time_max_BPLSD:",time_max_BPLSD)
            print("\n")    
        if show_prints:
            print("predicted observables_lsd:\n")
            print(predicted_error_lsd)    
        
        #BPOSD    
        a = time.time()
        predicted_error_osd = _bposd.decode(detectors[0])

        if show_times and pattern % 1000 == 0:
            time_bposd_decoding = time.time() - time_start
            print("Time for BPOSD decoding (pattern % 1000 == 0):", time_bposd_decoding)

        b = time.time()
        time_av_BPOSD += (b - a) / NMCs[index]
        if show_prints:
            print("time_av_BPOSD:",time_av_BPOSD)
        times_BPOSD[codeConfig].append(b-a)
        if show_prints:
            print("times_BPOSD:",times_BPOSD)
        time_max_BPOSD = max(time_max_BPOSD, (b - a))  
        if show_prints:
            print("time_max_BPOSD:",time_max_BPOSD)
            print("\n")    
        if show_prints:
            print("predicted observables_osd:\n")
            print(predicted_error_osd)    
        '''
        
        #Compute the logical error rate
        # ! DEBUG: Pintar tipos de datos
        # print("observable_mat type, shape:", type(observable_mat), observable_mat.shape)
        # print("observable_mat:\n", observable_mat)

        # print("predicted_error type, shape:", type(predicted_error), predicted_error.shape)
        # print("predicted_error:\n", predicted_error)

        # print("observables type, shape:", type(observables), observables.shape)
        # print("observables:\n", observables)
        
        logical_error = (observable_mat@predicted_error+observables) % 2
        # logical_error_lsd = (observable_mat@predicted_error_lsd+observables) % 2 
        # logical_error_osd = (observable_mat@predicted_error_osd+observables) % 2
        if show_prints:
            print("logical error:\n")
            print(logical_error)
        
        if np.any(logical_error == 1):
            PlBP += 1/NMCs[index]
            print(f'Error corrected in pattern {pattern}') # ! DEBUG
            # print(f'Error BP: {PlBP}')        
        # if np.any(logical_error_lsd == 1):
        #     PlBPLSD += 1/NMCs[index]  
        #     # print(f'Error BPLSD: {PlBPLSD}')     
        # if np.any(logical_error_osd == 1):
        #     PlBPOSD += 1/NMCs[index]  
        #     # print(f'Error BPOSD: {PlBPOSD}')                
        

    # Store results
    PlsBP[codeConfig].append(PlBP)
    # PlsBPLSD[codeConfig].append(PlBPLSD)
    # PlsBPOSD[codeConfig].append(PlBPOSD)
    

    print(f'Physical error: {p}')
    # print(f'Successful correction patterns (no logical error) for BP: {successful_correction_patterns}') # ! DEBUG
    print(f'Logical error BP: {PlBP} with average time {time_av_BP} and max time {time_max_BP}')
    # print(f'Error BPLSD: {PlBPLSD} with average time {time_av_BPLSD} and max time {time_max_BPLSD}')
    # print(f'Error BPOSD: {PlBPOSD} with average time {time_av_BPOSD} and max time {time_max_BPOSD}')
