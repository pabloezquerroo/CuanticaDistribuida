
""" 
Lambda que realiza las siguientes funciones:
1. Recibe number_of_args_combinations_batches, id_nmc_batch e id_batch_arguments.
2. Lee de S3 la configuración de simulación (código, p, NMCs, NMC_batch_size, args_batch_size).
3. Lee de samples_dynamodb la ruta a S3 y lee de S3 los arrays de detectores y observables.
4. Actualiza el campo workers_completed + 1.
    Si workers_completed >= number_of_args_combinations_batches => 
        - Se elimina el objeto de S3 al que hace referencia id_nmc_batch.
        - Se elimina la entrada id_nmc_batch de samples_dynamodb
5. Lee de args_dynamodb los argumentos de su lote (id_batch_arguments)
6. Realiza la ejecución completa con a partir de la información recibida para cada argumento.
7. Guarda en una BD cada resultado con id_arguments, id_nmc_batch, codigo, p.
"""

import os
import json
import numpy as np  
import time  

from ldpc import BpDecoder  
from ldpc.bplsd_decoder import BpLsdDecoder
from ldpc import BpOsdDecoder  
from dem_to_matrices import detector_error_model_to_check_matrices
from IBM_STIM import create_bivariate_bicycle_codes, build_circuit, select_configuration

import boto3
from boto3.dynamodb.conditions import Key

import logging
logging.basicConfig(level=logging.INFO)

import dotenv
dotenv.load_dotenv()

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

def get_config_from_s3(bucket_name, config_file_path):
    """Retrieve a configuration file from an S3 bucket.

    Args:
        bucket_name (str): The name of the S3 bucket.
        config_file_path (str): The path to the configuration file within the bucket.

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
        response = s3.get_object(Bucket=bucket_name, Key=config_file_path)
        dict_config = json.loads(response['Body'].read().decode('utf-8'))
        logging.info("Configuration loaded from S3.")
        return dict_config
    except Exception as e:
        logging.error(f"Error loading configuration from S3: {e}")
        return None

# TODO: Implementar
def get_samples_from_s3(s3_data_path):
    try:
        s3 = get_connection_s3()
        response = s3.get_object(Bucket=os.getenv('S3_BUCKET_NAME'), Key=s3_data_path)
        dict_samples = json.loads(response['Body'].read().decode('utf-8'))
        logging.info("Samples loaded from S3.")
        return dict_samples
    except Exception as e:
        logging.error(f"Error loading samples from S3: {e}")
        return None
#endregion

#region DynamoDB Functions
def get_connection_dynamodb():
    """Create and return a Boto3 DynamoDB resource.

    The configuration is loaded from environment variables.
    The endpoint_url is particularly important for local development.

    Returns:
        boto3.resource: A DynamoDB resource object.
    """
    return boto3.resource(
        'dynamodb',
        region_name=os.getenv('AWS_DEFAULT_REGION'),
        endpoint_url=os.getenv('DYNAMODB_ENDPOINT_URL')
    )

def get_samples_info_from_dynamodb(id_nmc_batch):
    """Get information about a batch of NMC samples from DynamoDB.

    This includes the S3 path to the samples file.

    Args:
        id_nmc_batch (str): The ID of the NMC batch.

    Returns:
        dict: The item from DynamoDB containing sample information, or None if an error occurs or the item is not found.
            For example:
            {
                "id_nmc_batch": "nmc_batch_1",
                "s3_data_path": "s3://bucket/nmc_batch_1.json",
                "workers_completed": 0
            }
    """
    try:
        dynamodb = get_connection_dynamodb()
        table = dynamodb.Table(os.getenv('DYNAMODB_SAMPLES_TABLE_NAME'))
        response = table.get_item(
            Key={
                'id_nmc_batch': id_nmc_batch,
            }
        )
        return response.get('Item')
    except Exception as e:
        logging.error(f"Error loading samples info from DynamoDB: {e}")
        return None    

def get_args_list_from_dynamodb(id_batch_arguments):
    """Retrieve a set of arguments from the DynamoDB arguments table.

    Args:
        id_batch_arguments (int): The ID of the arguments batch.

    Returns:
        list: A list of argument items from the DynamoDB arguments table, or an empty list if none are found.
    """
    try:
        dynamodb = get_connection_dynamodb()
        table = dynamodb.Table(os.getenv('DYNAMODB_ARGS_TABLE_NAME'))
        
        # Query the table for all items with the given id_batch_arguments
        response = table.query(
            KeyConditionExpression=Key('id_batch_arguments').eq(id_batch_arguments)
        )
        
        items = response.get('Items', [])
        
        if not items:
            logging.warning(f"No arguments found for id_batch_arguments: {id_batch_arguments}")
        else:
            logging.info(f"Successfully retrieved {len(items)} arguments for id_batch_arguments: {id_batch_arguments}")
            
        return items
        
    except Exception as e:
        logging.error(f"Error getting arguments from DynamoDB: {e}")
        return None

def add_workers_completed_to_dynamodb(id_nmc_batch):
    """Increment the 'workers_completed' counter for an NMC batch in DynamoDB.

    This is called when an args_worker finishes its job.

    Args:
        id_nmc_batch (str): The ID of the NMC batch to update.

    Returns:
        dict: The response from the update_item call, or None if an error occurs.
            For example:
            {
                "id_nmc_batch": "nmc_batch_1",
                "s3_data_path": "s3://bucket/nmc_batch_1.json",
                "workers_completed": 1
            }
    """
    try:
        dynamodb = get_connection_dynamodb()
        table = dynamodb.Table(os.getenv('DYNAMODB_SAMPLES_TABLE_NAME'))
        response = table.update_item(
            Key={
                'id_nmc_batch': id_nmc_batch,
            },
            UpdateExpression='SET workers_completed = workers_completed + :val',
            ExpressionAttributeValues={
                ':val': 1
            },
            ReturnValues='UPDATED_NEW'
        )
        return response
    except Exception as e:
        logging.error(f"Error adding workers completed to DynamoDB: {e}")
        return None
#endregion


def do_simulation(arguments, codeConfig, p, id_nmc_batch, detectors, observables, pcm, observable_mat, error_channel):

    if arguments.get("error_channel") == "dem_error_channel":
        arguments["error_channel"] = error_channel     # Prior error probabilities for each channel 

    # * Initialize decoders
    if arguments["decoder_type"] == "BP":
        _decoder = BpDecoder(pcm, error_rate=float(p), *arguments["arguments"])
    elif arguments["decoder_type"] == "BPLSD":
        _decoder = BpLsdDecoder(pcm, error_rate=float(p), *arguments["arguments"])
    elif arguments["decoder_type"] == "BPOSD":
        _decoder = BpOsdDecoder(pcm, error_rate=float(p), *arguments["arguments"])
    else:
        raise ValueError(f"Decoder type {arguments["decoder_type"]} not supported")

    # * Initialize results
    Pl = 0
    time_av = 0
    time_max = 0
    successful_correction_iterations = []

    
    # * Run Monte Carlo trials
    NMCs_size = len(detectors)
    for i in range(NMCs_size):
        a = time.time()
        predicted_observables = _decoder.decode(detectors[i])
        b = time.time()
        time_av += (b - a) / NMCs_size

        time_max = max(time_max, (b - a))

        logical_error = (observable_mat @ predicted_observables + observables[i]) % 2

        if np.any(logical_error):
            Pl += 1 / NMCs_size
            successful_correction_iterations.append(i)

    # * Results
    results = {
        "id_nmc_batch": id_nmc_batch, # ID of the NMC batch: nmc_{code}_{p(0c001)}_{nmc_batch_counter}
        "codeConfig": codeConfig, # Possible codes: 72, 90, 108, 144, 288, 784
        "p": p, # Error probability
        "decoder_type": arguments["decoder_type"], # Type of decoder
        "id_arguments": arguments["id_arguments"], # ID of the arguments used
        "arguments": arguments, # Arguments for the decoder
        "Pl": Pl, # Logical error detection probability in the batch
        "time_av": time_av, # Average decoding time in the batch
        "time_max": time_max, # Maximum decoding time in the batch
        "successful_correction_iterations": successful_correction_iterations # Iterations where the decoder successfully corrected the error
    }
    return results

def lambda_handler(event, context=None):

    # * Input variables
    # Event variables received from nmc_worker
    id_nmc_batch = event["id_nmc_batch"]
    number_of_args_combinations_batches = event["number_of_args_combinations_batches"]
    id_batch_arguments = event["id_batch_arguments"]

    # Simulation variables loaded from S3
    simulation_config = get_config_from_s3(os.getenv('S3_BUCKET_NAME'), os.getenv('S3_CONFIG_FILE_PATH'))
    codeConfig = simulation_config["codeConfig"]
    p = simulation_config["p"]

    # * Build quantum code
    # Parameters for simulation
    config = select_configuration(codeConfig)
    ell, m = config["ell"], config["m"]
    a1, a2, a3 = config["a"]
    b1, b2, b3 = config["b"]
    d = config["d"]

    # Construct the polynomials A and B for the code
    A_x_pows, A_y_pows = [a1], [a2, a3] 
    B_x_pows, B_y_pows = [b2, b3], [b1]
    code, A_list, B_list = create_bivariate_bicycle_codes(ell, m, A_x_pows, A_y_pows, B_x_pows, B_y_pows)

    # * Build circuit and detector error model
    circuit = build_circuit(code, A_list, B_list, p=p, num_repeat=d, z_basis=False, use_both=False)
    dem = circuit.detector_error_model()
    
    # * Convert detector error model to check matrices
    matrices = detector_error_model_to_check_matrices(dem, allow_undecomposed_hyperedges=True)
    pcm = matrices.check_matrix                     # Parity check matrix
    observable_mat = matrices.observables_matrix    # Logical observables matrix
    error_channel = matrices.priors

    # Args variables loaded from DynamoDB
    args_list = get_args_list_from_dynamodb(id_batch_arguments)

    # Detector and observable arrays loaded from S3
    samples_info = get_samples_info_from_dynamodb(id_nmc_batch)
    detectors, observables = get_samples_from_s3(samples_info["s3_data_path"])
    
    for arguments in args_list:
        results = do_simulation(arguments, codeConfig, p, id_nmc_batch, detectors, observables, pcm, observable_mat, error_channel)

        # TODO: Guardar los resultados en una BD

        for k, v in results.items():
            print(f"{k}: {v}")
        print("--------------------------------")
    
    # TODO: Incrementar workers_completed en DynamoDB y eliminar el objeto de S3 al que hace referencia id_nmc_batch si workers_completed = number_of_args_combinations_batches
