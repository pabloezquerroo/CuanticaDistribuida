import boto3
import json
import os
import dotenv
import logging
from IBM_STIM import select_configuration, create_bivariate_bicycle_codes, build_circuit

# Load environment variables from .env
dotenv.load_dotenv()

logging.basicConfig(level=logging.INFO)

def get_connection_s3():
    return boto3.client(
        's3',
        endpoint_url=os.getenv('S3_ENDPOINT_URL'),
        aws_access_key_id=os.getenv('S3_KEY_ID'),
        aws_secret_access_key=os.getenv('S3_APPLICATION_KEY')
    )

def get_config_from_s3():
    try:
        s3 = get_connection_s3()
        response = s3.get_object(Bucket=os.getenv('S3_BUCKET_NAME'), Key=os.getenv('CONFIG_FILE_PATH'))
        dict_config = json.loads(response['Body'].read().decode('utf-8'))
        logging.info("Configuration loaded from S3.")
        return dict_config
    except Exception as e:
        logging.error(f"Error loading configuration from S3: {e}")
        return None

def upload_to_s3(json_data, s3_key):
    try:
        s3 = get_connection_s3()
        s3.put_object(
            Bucket=os.getenv('S3_BUCKET_NAME'),
            Key=s3_key,
            Body=json.dumps(json_data).encode('utf-8'),
            ContentType='application/json'
        )
        logging.info("Data uploaded to S3.")
    except Exception as e:
        logging.error(f"Error uploading data to S3: {e}")

def main():
    # Get config from S3
    config_data = get_config_from_s3()

    if not config_data:
        logging.error("No configuration found in S3. Exiting.")
        return

    # Validate list lengths
    if len(config_data["NMCs"]) != len(config_data["p"]):
        logging.error("Error: The length of NMCs and p does not match.")
        return

    # Iterate over code configurations and error rates
    for code_config_val in config_data["codeConfig"]:
        for p_val_index, p_val in enumerate(config_data["p"]):
            logging.info(f"--- Processing codeConfig={code_config_val}, p={p_val} ---")

            # Build quantum code
            config = select_configuration(code_config_val)
            ell, m = config["ell"], config["m"]
            a1, a2, a3 = config["a"]
            b1, b2, b3 = config["b"]
            d = config["d"]

            A_x_pows, A_y_pows = [a1], [a2, a3]
            B_x_pows, B_y_pows = [b2, b3], [b1]
            code, A_list, B_list = create_bivariate_bicycle_codes(ell, m, A_x_pows, A_y_pows, B_x_pows, B_y_pows)

            # Build circuit
            circuit = build_circuit(code, A_list, B_list, p=p_val, num_repeat=d, z_basis=False, use_both=False)
            
            # Initialize lists for storing results
            all_detectors = []
            all_observables = []
            
            for i in range(config_data["NMCs"][p_val_index]):
                logging.info(f"Simulating {i+1} of {config_data['NMCs'][p_val_index]}...")
                sampler = circuit.compile_detector_sampler()
                detectors, observables = sampler.sample(1, separate_observables=True)
                
                all_detectors.append(detectors[0].tolist())
                all_observables.append(observables[0].tolist())

            results_for_config = {
                "detectors": all_detectors,
                "observables": all_observables
            }

            p_str = f"{p_val:.3f}".replace(".", "_")
            s3_key = os.path.join(os.getenv('DETECTORS_OBSERVABLES_PATH'), f"results_{code_config_val}_p{p_str}.json")

            upload_to_s3(results_for_config, s3_key)

            logging.info(f"Results for codeConfig={code_config_val}, p={p_val} saved to S3")
            

if __name__ == "__main__":
    main()
