import json
import os
import shortuuid
import requests

from dotenv import load_dotenv
from datetime import datetime
from fastapi import FastAPI, Form, Response, Request, HTTPException
from twilio.rest import Client
from twilio.request_validator import RequestValidator


load_dotenv()

TWILIO_ACCOUNT_SID = os.getenv('TWILIO_ACCOUNT_SID')
TWILIO_AUTH_TOKEN = os.getenv('TWILIO_AUTH_TOKEN')
NOTION_API_BASE_URL = 'https://api.notion.com/v1'
NOTION_API_TOKEN = os.getenv('NOTION_API_TOKEN')
NOTION_DATABASE_ID = os.getenv('NOTION_DATABASE_ID')
NOTION_REQ_HEADERS: dict = {
    'Authorization': f'Bearer {NOTION_API_TOKEN}',
    'Content-Type': 'application/json',
    'Notion-Version': '2021-08-16',
}


app = FastAPI()


def create_appointment(name: str, phone_no: str) -> str:
    uid = shortuuid.ShortUUID().random(length=6).lower()
    payload = {
        'parent': {
            'database_id': NOTION_DATABASE_ID
        },
        'properties': {
            'ID': {
                'rich_text': [
                    {
                        'type': 'text',
                        'text': {
                            'content': uid,
                        }
                    },
                ]
            },
            'Name': {
                'title': [
                    {
                        'type': 'text',
                        'text': {
                            'content': name
                        }
                    }
                ]
            },
            'Phone No.': {
                'phone_number': phone_no
            },
        },
    }

    # uses https://developers.notion.com/reference/retrieve-a-page
    response: Response = requests.post(
        f'{NOTION_API_BASE_URL}/pages', data=json.dumps(payload), headers=NOTION_REQ_HEADERS)

    if response.status_code == 200:
        return uid
    else:
        raise Exception(
            'Something went wrong while creating an appointment in Notion')


def get_appointment_details(uid: str) -> dict:
    payload = {
        'filter': {
            'property': 'ID',
            'rich_text': {
                'equals': uid
            }
        },
    }

    # uses https://developers.notion.com/reference/post-database-query
    response: Response = requests.post(
        f'{NOTION_API_BASE_URL}/databases/{NOTION_DATABASE_ID}/query', data=json.dumps(payload), headers=NOTION_REQ_HEADERS)

    if response.status_code == 200:
        json_response: dict = response.json()
        results = json_response['results']
        if len(results) > 0:
            appointment_details = results[0]
            appointment_date = appointment_details['properties']['Scheduled On']['date']
            return {
                'id': appointment_details['properties']['ID']['rich_text'][0]['plain_text'],
                'name': appointment_details['properties']['Name']['title'][0]['plain_text'],
                'phone_no': appointment_details['properties']['Phone No.']['phone_number'],
                'scheduled_on': datetime.fromisoformat(appointment_date['start']).strftime('%d %B, %Y at %I:%M %p') if appointment_date is not None else None
            }
    else:
        raise Exception(
            'Something went wrong while getting the appointment details from Notion')


def respond(to_number, message) -> None:
    twilio_client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

    # This is the Twilio Sandbox number. Don't change it.
    from_whatsapp_number = 'whatsapp:+14155238886',

    twilio_client.messages.create(body=message,
                                  from_=from_whatsapp_number,
                                  to=to_number)


async def validateWebhook(request: Request) -> None:
    validator = RequestValidator(TWILIO_AUTH_TOKEN)
    form_ = await request.form()
    if not validator.validate(
        str(request.url),
        form_,
        request.headers.get('X-Twilio-Signature', '')
    ):
        raise HTTPException(
            status_code=400, detail='Error in Twilio Signature')


@app.post('/message')
async def handle_message(request: Request, From: str = Form(...), Body: str = Form(...)) -> dict:
    await validateWebhook(request)

    if 'BOOK' in Body:
        args = Body.split(' ')
        name = args[1]
        phone_no = From.replace('whatsapp:', '')
        uid = create_appointment(name, phone_no)
        if uid:
            respond(
                From, f'An appointment has been created. Appointment ID is {uid}. Use this ID for any future communication.')

    elif 'STATUS' in Body:
        args = Body.split(' ')
        uid = args[1]
        status = get_appointment_details(uid)
        if status:
            if status['scheduled_on']:
                return respond(From, f"Your appointment is scheduled on {status['scheduled_on']}.")
            else:
                return respond(From, f'Your appointment is yet to be scheduled. Please check again later.')
        else:
            return respond(From, f'Your appointment could not be found.')

    else:
        return respond(From, 'Hi.\n\nTo create an appointment, send BOOK <name>\nTo get the status of your appointment, send STATUS <appointment_id>\n\nThanks')
