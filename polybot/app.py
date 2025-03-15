# Define required modules
import flask
from flask import request
import os
from bot import ObjectDetectionBot

import boto3
from botocore.exceptions import ClientError
from loguru import logger

app = flask.Flask(__name__)

# Code copied from aws credentials manager
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
    secret = get_secret_value_response['SecretString'] #secret is a dictionary of all secrets defined within the manager
    return secret

    # Your code goes here.
secrets_dict = get_secret()
logger.info(f'Secrets_dict: {secrets_dict} type : {type(secrets_dict)}')
TELEGRAM_TOKEN = secrets_dict["TELEGRAM_TOKEN"]
logger.info(f'TELEGRAM_TOKEN: {TELEGRAM_TOKEN}')

# TODO : This needs to be the LB's URL
TELEGRAM_APP_URL = os.environ['TELEGRAM_APP_URL']


@app.route('/', methods=['GET'])
def index():
    return 'Ok'


@app.route(f'/{TELEGRAM_TOKEN}/', methods=['POST'])
def webhook():
    req = request.get_json()
    bot.handle_message(req['message'])
    return 'Ok'


@app.route(f'/results', methods=['POST'])
def results():
    prediction_id = request.args.get('predictionId')

    # TODO use the prediction_id to retrieve results from MongoDB and send to the end-user

    chat_id = ...
    text_results = ...

    bot.send_text(chat_id, text_results)
    return 'Ok'


@app.route(f'/loadTest/', methods=['POST'])
def load_test():
    req = request.get_json()
    bot.handle_message(req['message'])
    return 'Ok'


if __name__ == "__main__":
    bot = ObjectDetectionBot(TELEGRAM_TOKEN, TELEGRAM_APP_URL)

    app.run(host='0.0.0.0', port=8443)
