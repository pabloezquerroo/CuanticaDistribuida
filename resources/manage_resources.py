import boto3
import os   
import dotenv

def get_dynamodb_client():
    return boto3.client(
        'dynamodb',
        region_name=os.getenv('AWS_DEFAULT_REGION'),
        endpoint_url=os.getenv('DYNAMODB_ENDPOINT_URL'),
        aws_access_key_id='dummy',
        aws_secret_access_key='dummy'
    )


def delete_all_dynamodb_tables():
    """
    Elimina todas las tablas de DynamoDB local
    """
    dynamodb_client = get_dynamodb_client()
    
    try:
        # Listar todas las tablas
        response = dynamodb_client.list_tables()
        
        if 'TableNames' in response and response['TableNames']:
            # Eliminar cada tabla
            for table_name in response['TableNames']:
                dynamodb_client.delete_table(TableName=table_name)
                print(f"Tabla '{table_name}' eliminada exitosamente.")
            
            print(f"Se eliminaron {len(response['TableNames'])} tablas de DynamoDB.")
        else:
            print("No hay tablas para eliminar en DynamoDB.")
            
    except Exception as e:
        print(f"Error al eliminar las tablas de DynamoDB: {e}")

def get_s3_client():
    return boto3.client(
        's3',
        endpoint_url=os.getenv('S3_ENDPOINT_URL'),
        region_name=os.getenv('AWS_DEFAULT_REGION'),
        aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
        aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY')
    )

def put_object(s3_client, bucket_name, object_key, data):
    s3_client.put_object(
        Bucket=bucket_name,
        Key=object_key,
        Body=data,
        ContentType='application/json'
    )

def upload_file_to_s3_config(filename):
    """
    Sube un archivo desde la carpeta actual a la carpeta config del bucket S3
    
    Args:
        filename (str): Nombre del archivo a subir
    """
    # El archivo está en la carpeta resources
    file_path = os.path.join(os.path.dirname(__file__), filename)
    
    try:
        s3_client = get_s3_client()
        # La key incluye el prefijo 'config/' para crear la estructura de carpetas
        s3_key = f"config/{filename}"
        
        # Leer el archivo
        with open(file_path, 'rb') as file:
            file_data = file.read()
            
        # Subir al bucket
        put_object(
            s3_client, 
            "quantum-cloud-data",  # Tu nombre de bucket definido en serverless.yml
            s3_key, 
            file_data
        )
        print(f"Archivo '{filename}' subido exitosamente a config/{filename}")
        
    except FileNotFoundError:
        print(f"Error: No se encontró el archivo '{filename}' en la ruta '{os.path.dirname(__file__)}'")
    except Exception as e:
        print(f"Error al subir el archivo: {e}")

def clean_s3_bucket(bucket_name):
    s3_client = get_s3_client()
    
    try:
        # Listar todos los objetos en el bucket
        response = s3_client.list_objects_v2(Bucket=bucket_name)
        if 'Contents' in response:
            deleted_count = 0
            for obj in response['Contents']:
                # Excluir objetos que estén en el directorio automorphisms/
                if not obj['Key'].startswith('automorphisms/'):
                    s3_client.delete_object(Bucket=bucket_name, Key=obj['Key'])
                    deleted_count += 1
            
            print(f"Bucket '{bucket_name}' limpiado exitosamente.")
            print(f"Se eliminaron {deleted_count} objetos (excluyendo directorio 'automorphisms/').")
        else:
            print(f"No hay objetos para eliminar en el bucket '{bucket_name}'.")
        
    except Exception as e:
        print(f"Error al limpiar el bucket '{bucket_name}': {e}")

if __name__ == "__main__":
    dotenv.load_dotenv()
    choice = -1

    # Menu de opciones
    print("Opciones:")
    print("1. Subir archivo a S3")
    print("2. Limpiar bucket S3")
    print("3. Eliminar todas las tablas de DynamoDB")
    print("0. Salir")

    while choice != '0':
        choice = input("Selecciona una opción (1-3): ")
        if choice == '1':
            upload_file_to_s3_config("config.json")
        elif choice == '2':
            clean_s3_bucket("quantum-cloud-data")
        elif choice == '3':
            delete_all_dynamodb_tables()

