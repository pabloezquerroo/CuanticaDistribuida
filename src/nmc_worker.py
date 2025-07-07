
""" 
Lambda que realiza las siguientes funciones:
1. Recibe id_nmc_batch y number_of_args_combinations_batches.
2. Invoca un args_worker por cada number_of_args_combinations_batches mandando id_nmc_batch, number_of_args_combinations_batches
e id_batch_arguments (distinto en cada invocación).
"""

import boto3
import os

import logging
logging.basicConfig(level=logging.INFO)

import dotenv
dotenv.load_dotenv()

def lambda_handler(event, context):
    id_nmc_batch = event['id_nmc_batch']
    number_of_args_combinations_batches = event['number_of_args_combinations_batches']
    
    for i in range(number_of_args_combinations_batches):
        event = {
            'id_nmc_batch': id_nmc_batch,
            'number_of_args_combinations_batches': number_of_args_combinations_batches,
            'id_batch_arguments': i
        }

        # TODO: Invocar a la lambda args_worker con el event
        
    return {"status": "ok"}
