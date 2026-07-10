import requests
r = requests.get('https://api.telegram.org/bot8260143148:AAH-FV3H62uk9DjIUQR_mrRBMs096gcepmg/getUpdates?offset=-1')
data = r.json()
for item in data.get('result', []):
    msg = item.get('message', {})
    chat = msg.get('chat', {})
    print('chat_id:', chat.get('id'))
    print('username:', chat.get('username'))
