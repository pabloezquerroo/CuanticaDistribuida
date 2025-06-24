import numpy as np  
import time  

# * STARTING TIME
time_start = time.time()
print("Starting time:", time_start)

SQS_msg = {
    "decoder_type": "BPOSD",
    "arguments": {"max_iter":100, "bp_method":"product_sum", "schedule":"parallel", "osd_method":"osd_0"},
    # TODO: "id_arguments": "123456789",
}

config = {
    "codeConfig": [72], # Posibles codigos: 72, 90, 108, 144, 288, 784
    "p": [0.001],  # Posibles tasas de error fisicas: 0.001, 0.002, 0.003, 0.004, 0.005
    "NMCs": [10**6],
    "NMCs_batch": 1000, # Numero de iteraciones por lote
}

for codeConfig in config["codeConfig"]:
    for physical_error_index, p in enumerate(config["p"]):
        number_of_NMCs_batch = config["NMCs"][physical_error_index] // config["NMCs_batch"]
        for batch_number in range(number_of_NMCs_batch):
            worker_event = {
                "codeConfig": codeConfig,
                "p": p,
                "NMCs_batch": config["NMCs_batch"],
                "decoder_type": config["decoder_type"],
                "arguments": config["arguments"],
                # TODO: Añadir ID concatenado de codeConfig, p, batch_number (ID = 123456789_72_001_1)
            }

            #TODO: invoke worker lambda
