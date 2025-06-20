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


if __name__ == "__main__":

    show_prints = False
    
    # List of codes to test
    codesConfig = ["72", "90", "108", "144", "288", "784"]
    
    # Number of Monte Carlo trials for each distance --> 100/pl(d) 
    
    NMCs = [10**6, 10**6, 10**6, 10**6, 10**6]  
    
    # ps --> LOGICAL ERROR PROBABILITY per syndrome cycle
    
    ps = np.linspace(0.001, 0.005, num=5)  
    
    print(ps)
    
    # Logical error rates for BP, BPLSD and BPOSD decoders
    PlsBP = {}  
    PlsBPLSD = {}  
    PlsBPOSD = {}  
    

    # Execution times for BP, BP+LSD, BP+OSD
    times_BPOSD = {}  
    times_BPLSD = {} 
    times_BP = {} 

    

    for codeConfig in codesConfig:
        
        # Parameters of a Bivariate Bicycle (BB) code
        # see Section 4 of https://arxiv.org/pdf/2308.07915.pdf for notations
        # The code is defined by a pair of polynomials
        # A and B that depends on two variables x and y such that
        # x^ell = 1
        # y^m = 1
        # A = x^{a_1} + y^{a_2} + y^{a_3} 
        # B = y^{b_1} + x^{b_2} + x^{b_3}
        
        # [[144,12,12]]
        #ell,m = 12,6
        #a1,a2,a3 = 3,1,2
        #b1,b2,b3 = 3,1,2

        # [[784,24,24]]
        #ell,m = 28,14
        #a1,a2,a3=26,6,8
        #b1,b2,b3=7,9,20

        # * El 6 del tercer parametro de la linea inferior equivale a la distancia
        # * que se define el la línea 120.
        # [[72,12,6]] 
        #ell,m = 6,6
        #a1,a2,a3=3,1,2
        #b1,b2,b3=3,1,2


        # Ted's code [[90,8,10]]
        #ell,m = 15,3
        #a1,a2,a3 = 9,1,2
        #b1,b2,b3 = 0,2,7

        # [[108,8,10]]
        #ell,m = 9,6
        #a1,a2,a3 = 3,1,2
        #b1,b2,b3 = 3,1,2

        # [[288,12,18]]
        #ell,m = 12,12
        #a1,a2,a3 = 3,2,7
        #b1,b2,b3 = 3,1,2


        # Select the configuration
        config = select_configuration(codeConfig)

        # Load the parameters
        ell, m = config["ell"], config["m"]
        a1, a2, a3 = config["a"]
        b1, b2, b3 = config["b"]

        A_x_pows, A_y_pows = [a1],[a2,a3] 
        B_x_pows, B_y_pows = [b2,b3], [b1]

        print(A_x_pows, A_y_pows)
        print(B_x_pows,B_y_pows)

        code, A_list, B_list = create_bivariate_bicycle_codes(ell, m, A_x_pows, A_y_pows, B_x_pows, B_y_pows)
        pcm = sparse.csc_matrix(code.hx, dtype=np.uint8)    
                
        # MODIFICAR
        d = 6
 
     

        # {3: []}
        PlsBP[codeConfig] = []
        PlsBPLSD[codeConfig] = []
        PlsBPOSD[codeConfig] = []
        times_BP[codeConfig] = []
        times_BPLSD[codeConfig] = []
        times_BPOSD[codeConfig] = []
       

        print(f'Code: {codeConfig}')
        print('-------------------------------------------------')
        for index, p in enumerate(ps):
            # Building the Stim circuit

            circuit = build_circuit(code, A_list, B_list, 
                        p=p, # physical error rate
                        num_repeat=d, # usually set to code distance
                        z_basis=False,   # whether in the z-basis or x-basis
                        use_both=False, # whether use measurement results in both basis to decode one basis
                        )

            dem = circuit.detector_error_model()
            
            # Proofs adapting the STIM to BP using as reference
            # https://github.com/oscarhiggott/stimbposd/blob/main/src/stimbposd/bp_osd.py 
            hx_shape = code.hx.shape
            if show_prints:
                print("hx_shape: ", hx_shape)
            hz_shape = code.hz.shape
            if show_prints:
                print("hz_shape: ", hz_shape)
            matrices = detector_error_model_to_check_matrices(dem, allow_undecomposed_hyperedges=True)
            num_detectors = dem.num_detectors
            if show_prints:
                print("Number of detectors: ", num_detectors)
            num_errors = dem.num_errors
            if show_prints:
                print("Number of errors: ", num_errors)
            h_shape = matrices.check_matrix.shape
            if show_prints:
                print("h_shape: ", h_shape)
            channel_probs=matrices.priors
            if show_prints:
                print("channel_probs= ", channel_probs)
                print("channel_probs is of size: ", channel_probs.shape)
            pcm=matrices.check_matrix
            if show_prints:
                print("pcm is of size: ", pcm.shape)
            observable_mat = matrices.observables_matrix
            
            
            if ldpc_v2 is True:

                # https://software.roffe.eu/ldpc/quantum_decoder.html               
                _bp = BpDecoder(pcm, max_iter=100, error_rate=float(p), bp_method="product_sum", error_channel=matrices.priors) #  error_channel antes era channel_probs
                _bplsd = BpLsdDecoder(pcm, max_iter=100, error_rate=float(p), bp_method="product_sum", osd_method = 'lsd_cs', osd_order = 2)
                _bposd = BpOsdDecoder(pcm, max_iter=100, error_rate=float(p), bp_method="product_sum", schedule = 'parallel', osd_method="osd_0")

                
            else:
                
                # https://software.roffe.eu/ldpc_v1/bp_decoding_example.html
                _bp = bp_decoder(pcm, max_iter=100, error_rate=float(p), bp_method="product_sum", channel_probs=matrices.priors)
                _bp0 = bp_decoder(pcm, max_iter=100, error_rate=float(p), bp_method="product_sum", channel_probs=matrices.priors)
                _bp1 = bp_decoder(pcm, max_iter=100, error_rate=float(p), bp_method="ms", ms_scaling_factor = 0.900, channel_probs=matrices.priors)
                _bp2 = bp_decoder(pcm, max_iter=100, error_rate=float(p), bp_method="ms", ms_scaling_factor = 0.750, channel_probs=matrices.priors)
                _bp3 = bp_decoder(pcm, max_iter=100, error_rate=float(p), bp_method="ms", ms_scaling_factor = 0.500, channel_probs=matrices.priors)
                _bposd = bposd_decoder(pcm, max_iter=100, error_rate=float(p), bp_method="product_sum", osd_method="osd_0")

            # Initialize variables for tracking performance
            PlBP, PlBPLSD, PlBPOSD = 0, 0, 0
            time_av_BP, time_max_BP = 0, 0
            time_av_BPOSD, time_max_BPOSD = 0, 0
            time_av_BPLSD, time_max_BPLSD = 0, 0
            


            for iteration in range(NMCs[index]):
                
                
                sampler = circuit.compile_detector_sampler()
                num_shots = 1
                detectors, observables = sampler.sample(num_shots, separate_observables=True)
                if show_prints:
                    print("detectors:\n")
                    print(detectors)
                    print("observables:\n")
                    print(observables)
                
                #BP
                a = time.time()  
                predicted_observables = _bp.decode(detectors[0])
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
            PlsBP[codeConfig].append(PlBP)
            PlsBPLSD[codeConfig].append(PlBPLSD)
            PlsBPOSD[codeConfig].append(PlBPOSD)
            

            print(f'Physical error: {p}')
            print(f'Logical error BP: {PlBP} with average time {time_av_BP} and max time {time_max_BP}')
            print(f'Error BPLSD: {PlBPLSD} with average time {time_av_BPLSD} and max time {time_max_BPLSD}')
            print(f'Error BPOSD: {PlBPOSD} with average time {time_av_BPOSD} and max time {time_max_BPOSD}')