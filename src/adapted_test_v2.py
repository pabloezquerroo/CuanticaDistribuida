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

from IBM_STIM import create_bivariate_bicycle_codes, build_circuit, select_configuration, save_sparse_matrices

# * STARTING TIME
time_start = time.time()
print("Starting time:", time_start)

# * DEBUG VARIABLE
show_prints = False
show_times = True


# * PARAMETERS FOR SIMULATION
# Codes to test
codesConfig = ["72", "90", "108", "144", "288", "784"]
codeConfig = codesConfig[0]  # Select one of the codes to test

# Number of Monte Carlo trials per physical error rate
NMCs = [10**6, 10**6, 10**6, 10**6, 10**6]  


# Physical error rates to simulate (between 0.1% and 0.5%)
ps = np.linspace(0.001, 0.005, num=5)


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
                        z_basis=False,   # whether in the z-basis or x-basis
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

    # https://software.roffe.eu/ldpc/quantum_decoder.html               
    _bp = BpDecoder(pcm, max_iter=100, error_rate=float(p), bp_method="product_sum", error_channel=dem_error_channel) #  error_channel antes era channel_probs
    _bplsd = BpLsdDecoder(pcm, max_iter=100, error_rate=float(p), bp_method="product_sum", osd_method = 'lsd_cs', osd_order = 2)
    _bposd = BpOsdDecoder(pcm, max_iter=100, error_rate=float(p), bp_method="product_sum", schedule = 'parallel', osd_method="osd_0")


    # Initialize variables for tracking performance
    PlBP, PlBPLSD, PlBPOSD = 0, 0, 0
    time_av_BP, time_max_BP = 0, 0
    time_av_BPOSD, time_max_BPOSD = 0, 0
    time_av_BPLSD, time_max_BPLSD = 0, 0
    
    if show_times:
        time_before_monte_carlo = time.time() - time_start
        print("Time until beginning of the Monte Carlo iterations:", time_before_monte_carlo)

    for iteration in range(NMCs[index]):
        
        if show_prints:
            time_init_iteration = time.time() - time_start
            print(f"Iteration {iteration + 1}/{NMCs[index]} for physical error rate {p} (time since start: {time_init_iteration} seconds)")

        # Generate aleatory samples of simulated errors
        sampler = circuit.compile_detector_sampler()
        num_shots = 1
        detectors, observables = sampler.sample(num_shots, separate_observables=True)
        if show_prints:
            print("detectors:\n")
            print(detectors)
            print("observables:\n")
            print(observables)

        if show_times:
            time_detectors_observables = time.time() - time_start
            print("Time to sample detectors and observables:", time_detectors_observables)
            
        #BP
        a = time.time()  
        predicted_observables = _bp.decode(detectors[0])

        if show_times:
            time_bp_decoding = time.time() - time_start
            print("Time for BP decoding:", time_bp_decoding)

        #soft_decisions = _bp.bp_decoding
        #convergence = _bp.converge
        #iteration_stop = _bp.iter
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
            print("predicted observables:\n")
            print(predicted_observables)
            
        #BPLSD    
        a = time.time()
        predicted_observables_lsd = _bplsd.decode(detectors[0])

        if show_times:
            time_bplsd_decoding = time.time() - time_start
            print("Time for BPLSD decoding:", time_bplsd_decoding)

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
            print(predicted_observables_lsd)    
        
        #BPOSD    
        a = time.time()
        predicted_observables_osd = _bposd.decode(detectors[0])

        if show_times:
            time_bposd_decoding = time.time() - time_start
            print("Time for BPOSD decoding:", time_bposd_decoding)

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
            print(predicted_observables_osd)    
        
        #Compute the logical error rate
        
        logical_error = (observable_mat@predicted_observables+observables) % 2
        logical_error_lsd = (observable_mat@predicted_observables_lsd+observables) % 2
        logical_error_osd = (observable_mat@predicted_observables_osd+observables) % 2
                        
        if show_prints:
            print("logical error:\n")
            print(logical_error)
        
        if np.any(logical_error == 1):
            PlBP += 1/NMCs[index]
            #print(f'Error BP: {PlBP}')        
        if np.any(logical_error_lsd == 1):
            PlBPLSD += 1/NMCs[index]  
            #print(f'Error BPLSD: {PlBPLSD}')     
        if np.any(logical_error_osd == 1):
            PlBPOSD += 1/NMCs[index]  
            #print(f'Error BPOSD: {PlBPOSD}')                
        
        
    # Store results
    PlsBP.append(PlBP)
    PlsBPLSD.append(PlBPLSD)
    PlsBPOSD.append(PlBPOSD)
    

    print(f'Physical error: {p}')
    print(f'Logical error BP: {PlBP} with average time {time_av_BP} and max time {time_max_BP}')
    print(f'Error BPLSD: {PlBPLSD} with average time {time_av_BPLSD} and max time {time_max_BPLSD}')
    print(f'Error BPOSD: {PlBPOSD} with average time {time_av_BPOSD} and max time {time_max_BPOSD}')
