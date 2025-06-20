import numpy as np  
import time  
from scipy import sparse 
from dem_to_matrices import detector_error_model_to_check_matrices
from IBM_STIM import create_bivariate_bicycle_codes, build_circuit, select_configuration
import os # For file local testing
import pickle

"""
Leemos variables pasados por evento de Lambda
- codeConfig: Código a probar
- NMCs_range: rango de Monte Carlo trials de este worker
- p: tasa de error física a simular 
- decoder_name: decodificador a usar
"""

# * STARTING TIME
time_start = time.time()

# * DEBUG VARIABLE
show_prints = False
show_times = True

# * PARAMETERS FOR SIMULATION
# Codes to test
codesConfig = ["72", "90", "108", "144", "288", "784"]
codeConfig = codesConfig[0]  # Select one of the codes to test
# Number of Monte Carlo trials
NMCs = [10**6, 10**6, 10**6, 10**6, 10**6]  
# Physical error rates to simulate (between 0.1% and 0.5%)
ps = np.linspace(0.001, 0.005, num=5)

# * BUILD QUANTUM CODE
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


# * LOOP OVER PHYSICAL ERROR RATES
for index, p in enumerate(ps):
    if show_prints:
        print(f"Running simulation for physical error rate: {p}")

    circuit = build_circuit(code, A_list, B_list, 
                        p=p, # physical error rate
                        num_repeat=d, # usually set to code distance
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

    for iteration in range(NMCs[index]):
        # ! Es necesario compilar el circuito cada vez?
        sampler = circuit.compile_detector_sampler()
        
        num_shots = 1
        detectors, observables = sampler.sample(num_shots, separate_observables=True)

        if show_prints:
            print("detectors:\n")
            print(detectors)
            print("observables:\n")
            print(observables)

    # Save the matrices to a pickle file
   

if show_times:
    end_time = time.time() - time_start
    print("End time of the pickle file generation:", end_time)