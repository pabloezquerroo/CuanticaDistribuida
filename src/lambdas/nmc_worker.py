
""" 
Lambda que realiza las siguientes funciones:
1. Recibe id_nmc_batch y number_of_args_combinations_batches.
2. Invoca un args_worker por cada number_of_args_combinations_batches mandando id_nmc_batch, number_of_args_combinations_batches
e id_batch_arguments (distinto en cada invocación).
"""

import boto3
from botocore.exceptions import ClientError
import json
import os

import logging
logging.basicConfig(level=logging.INFO)

import dotenv
dotenv.load_dotenv()


#region Lambda Functions
def get_connection_lambda():
    return boto3.client('lambda',
        region_name=os.getenv('AWS_DEFAULT_REGION'),
        endpoint_url=os.getenv('LAMBDA_ENDPOINT_URL'),
        aws_access_key_id='dummy',
        aws_secret_access_key='dummy'
    )

def invoke_lambda(lambda_client, payload, lambda_name):
    """Invoke the Lambda function.

    Args:
        payload (dict): The payload to send to the Lambda function.

    Returns:
        dict: The response from the Lambda function.
    """
    logging.info(f"Invoking Lambda with payload: {payload}")
    try:
        response = lambda_client.invoke(
            FunctionName=lambda_name,
            InvocationType='Event',
            Payload=json.dumps(payload)
        )
        logging.info(f"Lambda invoked with response: {response}")
        return response
    except ClientError as e:
        logging.error(f"Error invoking lambda: {e}")
        raise RuntimeError("Error invoking lambda") from e
    
#endregion


def lambda_handler(event, context):
    try:
        logging.info(f"Received event: {event}")
        id_nmc_batch = event['id_nmc_batch']
        if not id_nmc_batch:
            logging.error("id_nmc_batch is required. Exiting.")
            return {"status": "failed"}
        
        number_of_args_combinations_batches = event['number_of_args_combinations_batches']
        if number_of_args_combinations_batches < 1:
            logging.error("number_of_args_combinations_batches must be greater than 0. Exiting.")
            return {"status": "failed"}
        
        lambda_client = get_connection_lambda()
        for i in range(number_of_args_combinations_batches):
            event = {
                'id_nmc_batch': id_nmc_batch,
                'number_of_args_combinations_batches': number_of_args_combinations_batches,
                'id_batch_arguments': i
            }

            # ! TO TEST
            if not os.getenv('LAMBDA_ARGS_WORKER_NAME'):
                raise ValueError("LAMBDA_ARGS_WORKER_NAME no está definida en las variables de entorno")
            
            payload = {
                'id_nmc_batch': id_nmc_batch,
                'number_of_args_combinations_batches': number_of_args_combinations_batches
                }
            response = invoke_lambda(lambda_client, payload, os.getenv('LAMBDA_NMC_WORKER_NAME'))
            logging.info(f"nmc_worker invoked with response: {response}")

            logging.info(f"Invoking args_worker with event: {event}")
            
        return {"status": "ok"}
    except Exception as e:
        logging.error(f"Error in nmc_worker lambda_handler: {e}")
        return {"status": "failed"}
# if __name__ == "__main__":
#     id_nmc_batch = "nmc_90_0c001_1"
#     number_of_args_combinations_batches = 1 # ! Para pruebas sin eventos
#     try:
#         logging.info(f"Executing nmc_worker.py locally...")
#         lambda_handler({"id_nmc_batch": id_nmc_batch, "number_of_args_combinations_batches": number_of_args_combinations_batches}, None)
#         logging.info("Local execution finished.")
#     except Exception as e:
#         logging.error(f"Error in nmc_worker.py: {e}")
#         raise RuntimeError("Error in nmc_worker.py") from e
    