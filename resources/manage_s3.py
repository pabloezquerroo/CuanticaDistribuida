import boto3
import os   

def get_s3_client():
    return boto3.client(
        's3',
        endpoint_url='http://localhost:4569',  # Puerto por defecto del plugin
        aws_access_key_id='S3RVER',  # Credenciales dummy
        aws_secret_access_key='S3RVER',
        region_name='us-east-1'
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
    Sube un archivo desde la carpeta de descargas a la carpeta config del bucket S3
    
    Args:
        filename (str): Nombre del archivo en la carpeta de descargas
    """
    downloads_path = os.path.expanduser("~/Downloads")
    file_path = os.path.join(downloads_path, filename)
    
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
        print(f"Error: No se encontró el archivo '{filename}' en Descargas")
    except Exception as e:
        print(f"Error al subir el archivo: {e}")

def clean_s3_bucket(bucket_name):
    s3_client = get_s3_client()
    
    try:
        # Listar y eliminar todos los objetos en el bucket
        response = s3_client.list_objects_v2(Bucket=bucket_name)
        if 'Contents' in response:
            for obj in response['Contents']:
                s3_client.delete_object(Bucket=bucket_name, Key=obj['Key'])
        print(f"Bucket '{bucket_name}' limpiado exitosamente.")
        
    except Exception as e:
        print(f"Error al limpiar el bucket '{bucket_name}': {e}")

def delete_bucket(bucket_name):
    s3_client = get_s3_client()
    
    try:
        # Listar y eliminar todos los objetos en el bucket
        response = s3_client.list_objects_v2(Bucket=bucket_name)
        if 'Contents' in response:
            for obj in response['Contents']:
                s3_client.delete_object(Bucket=bucket_name, Key=obj['Key'])
        
        # Eliminar el bucket
        s3_client.delete_bucket(Bucket=bucket_name)
        print(f"Bucket '{bucket_name}' eliminado exitosamente.")
        
    except Exception as e:
        print(f"Error al eliminar el bucket '{bucket_name}': {e}")
        
if __name__ == "__main__":
    choice = -1

    # Menu de opciones
    print("Opciones:")
    print("1. Subir archivo a S3")
    print("2. Limpiar bucket S3")
    print("3. Eliminar bucket S3")
    print("0. Salir")

    while choice != '0':
        choice = input("Selecciona una opción (1-3): ")
        if choice == '1':
            upload_file_to_s3_config("config.json")
        elif choice == '2':
            clean_s3_bucket("quantum-cloud-data")
        elif choice == '3':
            delete_bucket("quantum-cloud-data")

