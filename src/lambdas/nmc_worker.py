
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
import requests

import logging
for handler in logging.root.handlers[:]:
    logging.root.removeHandler(handler)
logging.basicConfig(level=logging.INFO)

import dotenv
# dotenv.load_dotenv()


#region Lambda Functions
# def get_connection_lambda():
#     return boto3.client('lambda',
#         region_name=os.getenv('AWS_DEFAULT_REGION'),
#         endpoint_url=os.getenv('LAMBDA_ENDPOINT_URL'),
#         aws_access_key_id='dummy',
#         aws_secret_access_key='dummy'
#     )

def invoke_lambda(payload, lambda_name):
    """
    Invoke a Lambda function either locally or in AWS.

    Args:
        payload (dict): The payload to send to the Lambda function.
        lambda_name (str): The name of the Lambda function to invoke.
    Returns:
        dict: The response from the Lambda function.
    """
    is_offline = os.getenv("IS_OFFLINE", "false").lower() == "true"

    if is_offline:
        url = f"{os.getenv('LAMBDA_ENDPOINT_URL')}{lambda_name}"
        try:
            logging.info(f"[OFFLINE] Invoking lambda '{lambda_name}' at {url} with payload: {payload}")
            response = requests.post(url, json=payload)
            logging.info(f"[OFFLINE] Lambda invoked successfully. HTTP code: {response.status_code}")
            return {"status": "invoked"}
        except requests.RequestException as e:
            logging.error(f"[OFFLINE] Error invoking lambda via HTTP: {e}")
            raise RuntimeError("Error invoking lambda locally") from e
    else:
        try:
            logging.info(f"[AWS] Invoking lambda '{lambda_name}' via boto3 with payload: {payload}")
            lambda_client = boto3.client("lambda")
            response = lambda_client.invoke(
                FunctionName=lambda_name,
                InvocationType='Event',
                Payload=json.dumps(payload)
            )
            logging.info(f"[AWS] Lambda invoked. Status code: {response['StatusCode']}")
            return response
        except ClientError as e:
            logging.error(f"[AWS] Error invoking lambda via boto3: {e}")
            raise RuntimeError("Error invoking lambda on AWS") from e
    
#endregion


def lambda_handler(event, context):
    try:
        logging.info(f"Event received in nmc_worker lambda_handler")
        
        if "body" in event: # if the event comes from http (Local testing)
            received_event = json.loads(event["body"])
        else:               # if the event comes from AWS Lambda
            received_event = event

        id_nmc_batch = received_event.get("id_nmc_batch")
        if not id_nmc_batch:
            logging.error("id_nmc_batch is required. Exiting.")
            return {"status": "failed"}
        
        number_of_args_combinations_batches = received_event.get("number_of_args_combinations_batches")
        if number_of_args_combinations_batches < 1:
            logging.error("number_of_args_combinations_batches must be greater than 0. Exiting.")
            return {"status": "failed"}

        for i in range(number_of_args_combinations_batches):
            event = {
                'id_nmc_batch': id_nmc_batch,
                'number_of_args_combinations_batches': number_of_args_combinations_batches,
                'id_batch_arguments': i
            }

            if not os.getenv('LAMBDA_ARGS_WORKER_NAME'):
                raise ValueError("LAMBDA_ARGS_WORKER_NAME no está definida en las variables de entorno")

            response = invoke_lambda(event, os.getenv('LAMBDA_ARGS_WORKER_NAME'))
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
    