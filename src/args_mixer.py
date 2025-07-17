"""
Lambda que realiza las siguientes funciones:
1. Se lee args_batch_size del archivo de S3 para estructurar combinaciones de argumentos en lotes.
2. Se crean todas las posibles combinaciones de argumentos y se añaden a una DynamoDB.
3. Se invoca orchestrator.py con el número de lotes de combinaciones de argumentos guardados (number_of_args_combinations_batches).
"""

import os
import json
import boto3
from botocore.exceptions import ClientError
import math
import logging
logging.basicConfig(level=logging.INFO)

import dotenv

# TODO: Realizar lógica que genere todas las posibles combinaciones de argumentos a partir de una lista de argumentos generales y específicos para los decodificadores
def generate_args():
    args_list = [
        {
            "id_arguments": 0,
            "decoder_type": "BP",
            "arguments": {"max_iter":100, "bp_method":"product_sum", "error_channel":"dem_error_channel"}
        }, 
        {
            "id_arguments": 1,
            "decoder_type": "BPLSD",
            "arguments": {"max_iter":100, "bp_method":"product_sum", "osd_method":"lsd_cs", "osd_order":2}
        },
        {
            "id_arguments": 2,
            "decoder_type": "BPOSD",
            "arguments": {"max_iter":100, "bp_method":"product_sum", "schedule":"parallel", "osd_method":"osd_0"}
        }
    ]
    return args_list

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
                  "p": [0.001, 0.002],         
                  "NMCs": [100, 100],
                  "NMCs_batch_size": 10,       # Size of the NMCs batch
                  "args_batch_size": 10        # Size of the args batch
              }
    """
    try:
        s3 = get_connection_s3()
        response = s3.get_object(Bucket=bucket_name, Key=S3_CONFIG_FILE_PATH)
        dict_config = json.loads(response['Body'].read().decode('utf-8'))
        logging.info("Configuration loaded from S3.")
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

def create_table_args_dynamodb_if_not_exists():
    """Create a DynamoDB table args_dynamodb if it does not exist.

    Returns:
        table: The created table.
    """
    table_name = os.getenv('DYNAMODB_ARGS_TABLE_NAME')

    try:
        dynamodb = get_connection_dynamodb()
    except ClientError as e:
        logging.error(f"Error connecting to DynamoDB: {e}")
        raise RuntimeError("Error connecting to DynamoDB") from e

    try:
        logging.info(f"Checking if table '{table_name}' exists...")
        table = dynamodb.Table(table_name)
        table.load()
        logging.info(f"Table '{table_name}' already exists.")
        return table
    except ClientError as e:
        if e.response['Error']['Code'] == 'ResourceNotFoundException':
            logging.warning(f"Table '{table_name}' does not exist. Creating...")
            try:
                table = dynamodb.create_table(
                    TableName=table_name,
                    KeySchema=[
                        {'AttributeName': 'id_batch_arguments', 'KeyType': 'HASH'},
                        {'AttributeName': 'id_arguments', 'KeyType': 'RANGE'}
                    ],
                    AttributeDefinitions=[
                        {'AttributeName': 'id_batch_arguments', 'AttributeType': 'N'},
                        {'AttributeName': 'id_arguments', 'AttributeType': 'N'}
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

def lambda_handler(event, context):
    config = get_config_from_s3(os.getenv('S3_BUCKET_NAME'), os.getenv('S3_CONFIG_FILE_PATH'))  
    args_batch_size = config['args_batch_size']

    args_list = generate_args()
    number_of_args_combinations_batches = math.ceil(len(args_list) / args_batch_size)
        
    table = create_table_args_dynamodb_if_not_exists()

    for i, args in enumerate(args_list):
        id_batch_arguments = (i // args_batch_size)
        try:
            table.put_item(
                Item={
                    'id_batch_arguments': id_batch_arguments,
                    'id_arguments': args['id_arguments'],
                    'decoder_type': args['decoder_type'],
                    'arguments': args['arguments']
                },
                ConditionExpression='attribute_not_exists(id_batch_arguments) AND attribute_not_exists(id_arguments)'
            )
            logging.info(f"Item {i} loaded to table '{os.getenv('DYNAMODB_ARGS_TABLE_NAME')}'")
        except ClientError as e:
            if e.response['Error']['Code'] == 'ConditionalCheckFailedException':
                logging.error(f"Item with id_batch_arguments={id_batch_arguments} and id_arguments={args['id_arguments']} already exists. Skipping.")
            else:
                logging.error(f"Error loading item: {e.response['Error']['Message']}")
                raise RuntimeError("Error loading item") from e

    #TODO: Invocar a orchestrator.py con number_of_args_combinations_batches
    logging.info(f"Arguments successfully saved to table '{os.getenv('DYNAMODB_ARGS_TABLE_NAME')}'")

    return {"status": "ok"}


if __name__ == "__main__":
    dotenv.load_dotenv()
    try:
        logging.info("Executing args_mixer.py locally...")
        lambda_handler(None, None)
        logging.info("Local execution finished.")
    except Exception as e:
        logging.error(f"Error in args_mixer.py: {e}")
        raise RuntimeError("Error in args_mixer.py") from e
    