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
from botocore.exceptions import ClientError
from boto3.dynamodb.conditions import Key
import decimal

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

def get_samples_from_s3(bucket_name, s3_data_path):
    """Retrieve a set of samples from an S3 bucket.

    Args:
        bucket_name (str): The name of the S3 bucket.
        s3_data_path (str): The path to the samples file within the bucket.

    Returns:
        dict: A dictionary with the samples, or None if an error occurs.
              For example:
              {
                  "detectors": [...],
                  "observables": [...]
              }
    """
    try:
        s3 = get_connection_s3()
        response = s3.get_object(Bucket=bucket_name, Key=s3_data_path)
        dict_samples = json.loads(response['Body'].read().decode('utf-8'))
        logging.info("Samples loaded from S3.")
        dict_samples["detectors"] = np.array(dict_samples["detectors"])
        dict_samples["observables"] = np.array(dict_samples["observables"])
        return dict_samples
    except ClientError as e:
        logging.error(f"Error loading samples from S3: {e}")
        raise RuntimeError("Error loading samples from S3") from e

def delete_samples_from_s3(bucket_name, s3_data_path):
    """Delete a set of samples from an S3 bucket.

    Args:
        bucket_name (str): The name of the S3 bucket.
        s3_data_path (str): The path to the samples file within the bucket.

    Returns:
        bool: True if the samples were deleted successfully, False otherwise.
    """
    try:
        s3 = get_connection_s3()
        s3.delete_object(Bucket=bucket_name, Key=s3_data_path)
        logging.info("Samples deleted from S3.")
        return True
    except ClientError as e:
        logging.error(f"Error deleting samples from S3: {e}")
        raise RuntimeError("Error deleting samples from S3") from e
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
    except ClientError as e:
        logging.error(f"Error loading samples info from DynamoDB: {e}")
        raise RuntimeError("Error loading samples info from DynamoDB") from e    

def replace_decimals(obj):
    if isinstance(obj, list):
        for i in range(len(obj)):
            obj[i] = replace_decimals(obj[i])
        return obj
    elif isinstance(obj, dict):
        for k, v in obj.items():
            obj[k] = replace_decimals(v)
        return obj
    elif isinstance(obj, decimal.Decimal):
        if obj % 1 == 0:
            return int(obj)
        else:
            return float(obj)
    else:
        return obj


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
            for item in items:
                item["arguments"] = replace_decimals(item["arguments"])    
            logging.info(f"Successfully retrieved {len(items)} arguments for id_batch_arguments: {id_batch_arguments}")
        return items
    except ClientError as e:
        logging.error(f"Error getting arguments from DynamoDB: {e}")
        raise RuntimeError("Error getting arguments from DynamoDB") from e

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
        return response["Attributes"]["workers_completed"]
    except ClientError as e:
        logging.error(f"Error adding workers completed to DynamoDB: {e}")
        raise RuntimeError("Error adding workers completed to DynamoDB") from e
#endregion

def do_simulation(arguments, codeConfig, p, id_nmc_batch, detectors, observables, pcm, observable_mat, error_channel):

    if arguments.get("arguments", {}).get("error_channel") == "dem_error_channel":
        arguments["arguments"]["error_channel"] = error_channel
        
    # * Initialize decoders
    if arguments["decoder_type"] == "BP":
        logging.info(f"BP decoder initialized")
        _decoder = BpDecoder(pcm, error_rate=float(p), **arguments["arguments"])
    elif arguments["decoder_type"] == "BPLSD":
        logging.info(f"BPLSD decoder initialized")
        _decoder = BpLsdDecoder(pcm, error_rate=float(p), **arguments["arguments"])
    elif arguments["decoder_type"] == "BPOSD":
        logging.info(f"BPOSD decoder initialized")
        _decoder = BpOsdDecoder(pcm, error_rate=float(p), **arguments["arguments"])
    else:
        raise ValueError(f"Decoder type {arguments["decoder_type"]} not supported")

    # * Initialize results
    Pl = 0
    time_av = 0
    time_max = 0
    successful_correction_iterations = []
    
    # * Run Monte Carlo trials
    NMCs_size = len(detectors)
    logging.info(f"Running {NMCs_size} Monte Carlo trials")
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

    # Simulation variables extracted from id_nmc_batch
    codeConfig = int(id_nmc_batch.split("_")[1])
    p = float(id_nmc_batch.split("_")[2].replace("c", "."))

    logging.info(f"codeConfig: {codeConfig}, p: {p}")

    # * Build quantum code
    # Parameters for simulation
    config = select_configuration(codeConfig)
    ell, m = config["ell"], config["m"]
    a1, a2, a3 = config["a"]
    b1, b2, b3 = config["b"]
    d = config["d"]
    logging.info(f"Config with codeConfig {codeConfig} loaded")
    # Construct the polynomials A and B for the code
    A_x_pows, A_y_pows = [a1], [a2, a3] 
    B_x_pows, B_y_pows = [b2, b3], [b1]
    code, A_list, B_list = create_bivariate_bicycle_codes(ell, m, A_x_pows, A_y_pows, B_x_pows, B_y_pows)
    logging.info(f"Bivariate bicycle code created")
    # ! ¿Por qué se calcula pcm aquí si luego se calcula de nuevo?
    # pcm = sparse.csc_matrix(code.hx, dtype=np.uint8)

    # * Build circuit and detector error model
    circuit = build_circuit(code, A_list, B_list, p=p, num_repeat=d, z_basis=False, use_both=False)
    logging.info(f"Circuit built")
    dem = circuit.detector_error_model()
    logging.info(f"Detector error model built")
    
    # * Convert detector error model to check matrices
    matrices = detector_error_model_to_check_matrices(dem, allow_undecomposed_hyperedges=True)
    logging.info(f"Detector error model converted to check matrices")
    pcm = matrices.check_matrix                     # Parity check matrix
    observable_mat = matrices.observables_matrix    # Logical observables matrix
    error_channel = matrices.priors

    # Args variables loaded from DynamoDB
    args_list = get_args_list_from_dynamodb(id_batch_arguments)
    logging.info(f"Args variables loaded from DynamoDB")

    # Detector and observable arrays loaded from S3
    samples_info = get_samples_info_from_dynamodb(id_nmc_batch)
    detectors, observables = get_samples_from_s3(os.getenv('S3_BUCKET_NAME'), samples_info["s3_data_path"]).values()
    
    for arguments in args_list:
        results = do_simulation(arguments, codeConfig, p, id_nmc_batch, detectors, observables, pcm, observable_mat, error_channel)
        
        # TODO: Guardar los resultados en una BD
        print("--------------------------------")
        for k, v in results.items():
            print(f"{k}: {v}")
        print("--------------------------------")
    
    if add_workers_completed_to_dynamodb(id_nmc_batch) >= number_of_args_combinations_batches:
        delete_samples_from_s3(os.getenv('S3_BUCKET_NAME'), samples_info["s3_data_path"])

    return {"status": "ok"}

if __name__ == "__main__":
    id_nmc_batch = "nmc_90_0c001_1"
    number_of_args_combinations_batches = 1
    id_batch_arguments = 0
    try:
        logging.info(f"Executing args_worker.py locally...")
        lambda_handler({"id_nmc_batch": id_nmc_batch, "number_of_args_combinations_batches": number_of_args_combinations_batches, "id_batch_arguments": id_batch_arguments}, None)
        logging.info("Local execution finished.")
    except Exception as e:
        logging.error(f"Error in args_worker.py: {e}")
        raise RuntimeError("Error in args_worker.py") from e
