import boto3
import json

def lambda_handler(event, context):
    # * STARTING TIME

    SQS_msg = {
        "decoder_type": "BPOSD",
        "arguments": {"max_iter":100, "bp_method":"product_sum", "schedule":"parallel", "osd_method":"osd_0"},
        "id_arguments": "123456789",
    }

    # TODO: Idealmente, esta configuración se obtiene de S3. Que a su vez actua de disparador para la Lambda 'argsmixer-lambda'
    config = { 
        "codeConfig": [72], # Posibles codigos: 72, 90, 108, 144, 288, 784
        "p": [0.001],  # Posibles tasas de error fisicas: 0.001, 0.002, 0.003, 0.004, 0.005
        "NMCs": [10**6],
        "NMCs_batch": 1000, # Numero de iteraciones por lote
    }

    lambda_client = boto3.client('lambda')

    for codeConfig in config["codeConfig"]:
        for physical_error_index, p in enumerate(config["p"]):
            number_of_NMCs_batch = config["NMCs"][physical_error_index] // config["NMCs_batch"]
            for batch_number in range(number_of_NMCs_batch):
                id_batch = f"{SQS_msg['id_arguments']}_{codeConfig}_{p}_{batch_number}"  # ? Ejemplo: ID = 123456789_72_001_1
                worker_event = {
                    "codeConfig": codeConfig,
                    "p": p,
                    "NMCs_batch": config["NMCs_batch"],
                    "decoder_type": SQS_msg["decoder_type"],
                    "arguments": SQS_msg["arguments"],
                    "id_batch": id_batch,
                }

                # * Async invocation of worker-lambda
                response = lambda_client.invoke(
                    FunctionName='worker-lambda',
                    InvocationType='Event', 
                    Payload=json.dumps(worker_event),
                )
                print(f"Invocada worker-lambda para batch {id_batch}, response: {response['StatusCode']}")

    return {"status": "ok"}