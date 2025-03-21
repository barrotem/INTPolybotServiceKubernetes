import time
from pathlib import Path
from detect import run
import yaml
from loguru import logger
import json
import os
# Define aws related modules
import boto3
from botocore.exceptions import ClientError
# Define polybot microservices related modules
import pymongo


def get_secret():
    secret_name = "barrotem/polybot/k8s-project"
    region_name = "eu-north-1"

    # Create a Secrets Manager client
    session = boto3.session.Session()
    client = session.client(
        service_name='secretsmanager',
        region_name=region_name
    )

    try:
        get_secret_value_response = client.get_secret_value(
            SecretId=secret_name
        )
    except ClientError as e:
        raise e
    secret = get_secret_value_response[
        'SecretString']  #secret is a dictionary of all secrets defined within the manager
    return secret


# Load secrets from AWS Secret Manager
secrets_dict = json.loads(get_secret())
# Access secrets loaded from secret manager
images_bucket = secrets_dict["IMAGES_BUCKET"]
queue_name = secrets_dict["POLYBOT_QUEUE"]
region_name = secrets_dict["DEPLOYED_REGION"]

# Initialize AWS clients for image processing
s3_client = boto3.client('s3')
sqs_client = boto3.client('sqs', region_name=region_name)
# Initialize polybot microservices related variables
MONGO_URI = "mongodb://mongodb-statefulset-0.mongodb-service:27017,mongodb-statefulset-1.mongodb-service:27017,mongodb-statefulset-2.mongodb-service:27017/test?replicaSet=mongo_rs"
mongo_client = pymongo.MongoClient(MONGO_URI)

with open("data/coco128.yaml", "r") as stream:
    names = yaml.safe_load(stream)['names']


def consume():
    while True:
        response = sqs_client.receive_message(QueueUrl=queue_name, MaxNumberOfMessages=1, WaitTimeSeconds=5)

        if 'Messages' in response:
            raw_message = response['Messages'][0]
            message = response['Messages'][0]['Body']
            receipt_handle = response['Messages'][0]['ReceiptHandle']

            # Use the ReceiptHandle as a prediction UUID
            prediction_id = response['Messages'][0]['MessageId']
            #logger.info(f'raw_message: {raw_message}')

            # Log relevant information to the console
            logger.info(f'prediction: {prediction_id}. start processing')
            logger.info(f'message: {message}, receipt_handle : {receipt_handle}')

            # Receives a URL parameter representing the image to download from S3
            # message_dict is built by the following syntax :
            # {"text": "A new image was uploaded to the s3 bucket", "img_name": s3_photo_key, "chat_id": chat_id}
            message_dict = json.loads(message)
            img_name = message_dict["img_name"]
            chat_id = message_dict["chat_id"]

            # Download image from s3
            folder_name = img_name.split('/')[0]
            if not os.path.exists(folder_name):
                os.makedirs(folder_name)
            s3_client.download_file(Bucket=images_bucket, Key=img_name, Filename=img_name)
            original_img_path = img_name
            original_img_name =  original_img_path.split("/")[1] # Represents the image's final path component - it's name

            logger.info(f'prediction: {prediction_id}/{original_img_path}. Download img completed')

            # Predicts the objects in the image
            run(
                weights='yolov5s.pt',
                data='data/coco128.yaml',
                source=original_img_path,
                project='static/data',
                name=prediction_id,
                save_txt=True
            )

            logger.info(f'prediction: {prediction_id}/{original_img_path}. done')
            # This is the path for the predicted image with labels
            # The predicted image typically includes bounding boxes drawn around the detected objects,
            # along with class labels and possibly confidence scores.

            predicted_img_path = Path(f'static/data/{prediction_id}/{original_img_name}')  # Yolo5 saves predicted image to a path determined by image filename only

            # Upload the predicted image to s3
            predicted_img_key = f'predictions/{original_img_name}'  # Taking img_name suffix into account, this creates : "prediction/filename.filetype"
            s3_client.upload_file(Filename=predicted_img_path, Bucket=images_bucket, Key=predicted_img_key)
            logger.info(f'prediction: {prediction_id}/{original_img_path} uploaded to s3 with the key: {predicted_img_key}.')

            # Parse prediction labels and create a summary
            pred_summary_path = Path(f'static/data/{prediction_id}/labels/{original_img_name.split(".")[0]}.txt')
            if pred_summary_path.exists():
                with open(pred_summary_path) as f:
                    labels = f.read().splitlines()
                    labels = [line.split(' ') for line in labels]
                    labels = [{
                        'class': names[int(l[0])],
                        'cx': float(l[1]),
                        'cy': float(l[2]),
                        'width': float(l[3]),
                        'height': float(l[4]),
                    } for l in labels]

                logger.info(f'prediction: {prediction_id}/{original_img_path}. prediction summary:\n\n{labels}')

                prediction_summary = {
                    'prediction_id': prediction_id,
                    'original_img_path': original_img_path,
                    'predicted_img_path': str(predicted_img_path),
                    'labels': labels,
                    'time': time.time()
                }

                logger.info(f'storing prediction_summary in mongodb...')
                test_db_client = mongo_client["test"]
                predictions_collection = test_db_client["predictions"]
                # Store a prediction inside the predictions collections
                document = {"_id": prediction_id, "prediction_summary": prediction_summary} # Allow fast indexing using prediction_id as the table's primary_key
                write_result = predictions_collection.insert_one(document)
                logger.info(f'Mongodb write result: {write_result}')
                # TODO store the prediction_summary in a MongoDB table
                # TODO perform a GET request to Polybot to `/results` endpoint

            # Delete the message from the queue as the job is considered as DONE
            logger.info(f'Deleting message {receipt_handle} from sqs, image processed successfully')
            sqs_client.delete_message(QueueUrl=queue_name, ReceiptHandle=receipt_handle)


if __name__ == "__main__":
    try:
        consume()
    except Exception as e:
        print(e)
