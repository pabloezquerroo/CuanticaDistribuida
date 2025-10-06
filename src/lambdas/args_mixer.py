"""
Lambda que realiza las siguientes funciones:
1. Se lee args_batch_size del archivo de S3 para estructurar combinaciones de argumentos en lotes.
2. Se crean argumentos para todos los automorfismos guardados en S3 y se añaden a una DynamoDB.
3. Se invoca orchestrator.py con el número de lotes de combinaciones de argumentos guardados (number_of_args_combinations_batches).
"""

import os
import json
import boto3
from botocore.exceptions import ClientError
import math
import requests
from decimal import Decimal

import logging
for handler in logging.root.handlers[:]:
    logging.root.removeHandler(handler)
logging.basicConfig(level=logging.INFO)

import dotenv

# TODO: Realizar lógica que genere todas las posibles combinaciones de argumentos a partir de una lista de argumentos generales y específicos para los decodificadores
def generate_args(config):
    args_list = [
        {
            "id_automorphism": 0,
            "id_arguments": "DUMMY",
            "decoder_type": "BP",
            "arguments": {"max_iter": 100, "ms_scaling_factor": Decimal('0.9'), "bp_method": "minimum_sum"}
        }, 
        # {
        #     "id_arguments": 0,
        #     "decoder_type": "BP",
        #     "arguments": {"max_iter":100, "bp_method":"product_sum", "error_channel":"dem_error_channel"}
        # }, 
        # {
        #     "id_arguments": 1,
        #     "decoder_type": "BPLSD",
        #     "arguments": {"max_iter":100, "bp_method":"product_sum", "osd_method":"lsd_cs", "osd_order":2}
        # },
        # {
        #     "id_arguments": 2,
        #     "decoder_type": "BPOSD",
        #     "arguments": {"max_iter":100, "bp_method":"product_sum", "schedule":"parallel", "osd_method":"osd_0"}
        # }
    ]
    return args_list

# AUTOMORFISMOS
# def generate_args(config):
#     number_of_automorphisms = config['number_of_automorphisms']
#     args_list = []
#     for i in range(number_of_automorphisms):
#         args_list.append(
#             {
#                 "id_automorphism": i,
#                 "id_arguments": f"BP_{i}",
#                 "decoder_type": "BP",
#                 "arguments": {"max_iter": 100, "ms_scaling_factor": Decimal('0.9'), "bp_method": "minimum_sum"}
#             }
#         )
#     return args_list

#region S3 Functions
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

def get_config_from_s3(bucket_name, S3_CONFIG_FILE_PATH):
    """Retrieve a configuration file from an S3 bucket.

    Args:
        bucket_name (str): The name of the S3 bucket.
        S3_CONFIG_FILE_PATH (str): The path to the configuration file within the bucket.

    Returns:
        dict: A dictionary with the configuration, or None if an error occurs.
              For example:
              {
                  "codeConfig": [72, 90],      # Possible codes: 72, 90, 108, 144, 288, 784
                  "NMCs": [100, 100],
                  "p": [0.001],
                  "number_of_automorphisms": 72,
                  "NMCs_batch_size": 10,       # Size of the NMCs batch
                  "args_batch_size": 10        # Size of the args batch
              }
    """
    try:
        s3 = get_connection_s3()
        response = s3.get_object(Bucket=bucket_name, Key=S3_CONFIG_FILE_PATH)
        dict_config = json.loads(response['Body'].read().decode('utf-8'))
        logging.info("Configuration loaded from S3.")
        
        if dict_config['codeConfig'] is None:
            logging.error("codeConfig not found in configuration. Exiting.")
            return {"status": "failed"}
        if dict_config["NMCs"] is None:
            logging.error("NMCs not found in configuration. Exiting.")
            return {"status": "failed"}
        if len(dict_config['codeConfig']) != len(dict_config['NMCs']):
            logging.error("codeConfig and NMCs must have the same number of elements. Exiting.")
            return {"status": "failed"}
        
        if dict_config["p"] is None:
            logging.error("p not found in configuration. Exiting.")
            return {"status": "failed"}
        if dict_config['number_of_automorphisms'] < 1:
            logging.error("number_of_automorphisms must be greater than 0. Exiting.")
            return {"status": "failed"}

        if dict_config['NMCs_batch_size'] is None or dict_config['NMCs_batch_size'] < 1:
            logging.error("NMCs_batch_size must be greater than 0. Exiting.")
            return {"status": "failed"}
        if dict_config['args_batch_size'] is None or dict_config['args_batch_size'] < 1:
            logging.error("args_batch_size must be greater than 0. Exiting.")
            return {"status": "failed"}
        
        return dict_config
    except ClientError as e:
        logging.error(f"Error loading configuration from S3: {e}")
        raise RuntimeError("Error loading configuration from S3") from e
#endregion
    
#region DynamoDB Functions
def get_connection_dynamodb():
    return boto3.resource(
        'dynamodb',
        region_name=os.getenv('AWS_DEFAULT_REGION'),
        endpoint_url=os.getenv('DYNAMODB_ENDPOINT_URL'),
        aws_access_key_id='dummy',
        aws_secret_access_key='dummy'
    )

def create_table_args_dynamodb_if_not_exists(dynamodb, table_name):
    """Create a DynamoDB table args_dynamodb if it does not exist.
    Args:
        table_name (str): The name of the DynamoDB table to create.
    Returns:
        table: The created table.
    """

    try:
        logging.info(f"Checking if table '{table_name}' exists...")
        table = dynamodb.Table(table_name)
        table.load()
        logging.info(f"Table '{table_name}' already exists.")
        return table
    except ClientError as e:
        if e.response['Error']['Code'] == 'ResourceNotFoundException':
            logging.info(f"Table '{table_name}' does not exist. Creating...")
            try:
                table = dynamodb.create_table(
                    TableName=table_name,
                    KeySchema=[
                        {'AttributeName': 'id_batch_arguments', 'KeyType': 'HASH'},
                        {'AttributeName': 'id_arguments', 'KeyType': 'RANGE'}
                    ],
                    AttributeDefinitions=[
                        {'AttributeName': 'id_batch_arguments', 'AttributeType': 'N'},
                        {'AttributeName': 'id_arguments', 'AttributeType': 'S'}
                    ],
                    ProvisionedThroughput={
                        'ReadCapacityUnits': 5,
                        'WriteCapacityUnits': 5
                    }
                )
                table.wait_until_exists()
                logging.info(f"Table '{table_name}' created successfully.")
                return table
            except ClientError as e2:
                logging.error(f"Error creating table '{table_name}': {e2}")
                raise RuntimeError("Error creating table") from e2
        else:
            logging.error(f"Unexpected error when checking table '{table_name}': {e}")
            raise RuntimeError("Error checking table existence") from e

#endregion

#region Lambda Functions
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
        config = get_config_from_s3(os.getenv('S3_BUCKET_NAME'), os.getenv('S3_CONFIG_FILE_PATH')) 
        if not config:
            logging.error("No configuration found in S3. Exiting.")
            return {"status": "failed"}

        args_list = generate_args(config)
        if len(args_list) < 1:
            logging.error("No args to process. Exiting.")
            return {"status": "failed"}
        
        args_batch_size = config['args_batch_size']
        number_of_args_combinations_batches = math.ceil(len(args_list) / args_batch_size)
        
        if os.getenv('DYNAMODB_ARGS_TABLE_NAME') is None:
            raise ValueError("DYNAMODB_ARGS_TABLE_NAME is not defined in environment variables")
        

        try:
            dynamodb = get_connection_dynamodb()
        except ClientError as e:
            logging.error(f"Error connecting to DynamoDB: {e}")
            raise RuntimeError("Error connecting to DynamoDB") from e
        
        # ! SOLO PARA PRUEBAS LOCALES - Comprobación de que la tabla existe o se crea si no existe.
        table = create_table_args_dynamodb_if_not_exists(dynamodb, os.getenv('DYNAMODB_ARGS_TABLE_NAME'))

        # ! EN PRODUCCIÓN - Se asume que la tabla ya existe.
        # table = dynamodb.Table(os.getenv('DYNAMODB_ARGS_TABLE_NAME'))

        for i, args in enumerate(args_list):
            id_batch_arguments = (i // args_batch_size)
            try:
                table.put_item(
                    Item={
                        'id_batch_arguments': id_batch_arguments,
                        'id_arguments': args['id_arguments'],
                        'id_automorphism': args['id_automorphism'],
                        'decoder_type': args['decoder_type'],
                        'arguments': args['arguments']
                    },
                    ConditionExpression='attribute_not_exists(id_batch_arguments) AND attribute_not_exists(id_arguments)'
                )
                logging.info(f"Item {i} (id_automorphism {args['id_automorphism']}) loaded to table '{os.getenv('DYNAMODB_ARGS_TABLE_NAME')}'")
            except ClientError as e:
                if e.response['Error']['Code'] == 'ConditionalCheckFailedException':
                    logging.error(f"Item with id_batch_arguments={id_batch_arguments} and id_arguments={args['id_arguments']} already exists. Skipping.")
                else:
                    logging.error(f"Error loading item: {e.response['Error']['Message']}")
                    raise RuntimeError("Error loading item") from e

        if not os.getenv('LAMBDA_ORCHESTRATOR_NAME'):
            raise ValueError("LAMBDA_ORCHESTRATOR_NAME no está definida en las variables de entorno")
        
        event = {
            'number_of_args_combinations_batches': number_of_args_combinations_batches
        }
        response = invoke_lambda(event, os.getenv('LAMBDA_ORCHESTRATOR_NAME'))
        logging.info(f"Orchestrator invoked with response: {response}")

        return {"status": "ok"}
    except Exception as e:
        logging.error(f"Error in args_mixer lambda_handler: {e}")
        return {"status": "failed"}

# if __name__ == "__main__":
#     dotenv.load_dotenv()
#     try:
#         logging.info("Executing args_mixer.py locally...")
#         lambda_handler(None, None)
#         logging.info("Local execution finished.")
#     except Exception as e:
#         logging.error(f"Error in args_mixer.py: {e}")
#         raise RuntimeError("Error in args_mixer.py") from e
    