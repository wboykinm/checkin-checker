import editdistance
import os
import requests
from flask import Flask, request, render_template, json

# configuration
# DEBUG = True
SECRET_KEY = 'development key'
MAILGUN_URL_BASE = os.environ.get('MAILGUN_URL_BASE')
MAILGUN_API_KEY = os.environ.get('MAILGUN_API_KEY')
MAILGUN_API_DOMAIN = os.environ.get('MAILGUN_API_DOMAIN')
FOURSQUARE_CLIENT_ID = os.environ.get('FOURSQUARE_CLIENT_ID')
FOURSQUARE_CLIENT_SECRET = os.environ.get('FOURSQUARE_CLIENT_SECRET')
APPLICATION_ROOT = os.environ.get('APPLICATION_ROOT')


# create our little application :)
application = Flask(__name__)
application.config.from_object(__name__)


def send_email(to, subject, body):
    response = requests.post(
        'https://api.mailgun.net/v3/{}/messages'.format(MAILGUN_API_DOMAIN),
        auth=('api', MAILGUN_API_KEY),
        data={
            "from": "Checkin Checker <ian@openstreetmap.us>",
            "to": to,
            "subject": subject,
            "text": body,
        }
    )
    response.raise_for_status()
    print response.json()


@application.route('/')
def index():
    callback_url = 'https://openstreetmap.us/checkins/auth/callback/foursquare'
    return render_template('index.html', callback_url=callback_url)


@application.route('/auth/callback/foursquare')
def foursquare_auth_callback():
    code = request.args.get('code')
    if code:
        print "Exchanging code for access token"
        response = requests.get(
            "https://foursquare.com/oauth2/access_token",
            params=dict(
                client_id=FOURSQUARE_CLIENT_ID,
                client_secret=FOURSQUARE_CLIENT_SECRET,
                grant_type='authorization_code',
                redirect_uri='https://openstreetmap.us/checkins/auth/callback/foursquare',
                code=code,
            )
        )
        response.raise_for_status()
        access_token = response.json().get('access_token')
        print "Got access token: {}".format(access_token)

        response = requests.get(
            "https://api.foursquare.com/v2/users/self",
            params=dict(
                oauth_token=access_token,
                v='20151108',
            )
        )
        response.raise_for_status()
        user_data = response.json()['response']['user']
        email = user_data.get('contact', {}).get('email')
        if email:
            message = "Hi {name},\n\n" \
                "You just connected your Foursquare account to Checkin Checker. " \
                "If you ever want to disconnet, go to https://foursquare.com/settings/connections and remove the Checkin Checker app.\n\n" \
                "Checkin Checker".format(
                    name=user_data.get('firstName'),
                )
            send_email(email, "Welcome to Checkin Checker", message)

    return render_template('auth_callback_foursquare.html')


@application.route('/hooks/foursquare', methods=['POST'])
def foursquare_webhook():
    checkin = json.loads(request.form.get('checkin'))
    user = json.loads(request.form.get('user'))

    venue = checkin.get('venue')
    venue_name = venue.get('name')

    query = '[out:json][timeout:5];(' \
        'node["name"](around:100.0,{lat},{lng});' \
        'way["name"](around:100.0,{lat},{lng});' \
        'relation["name"](around:100.0,{lat},{lng});' \
        ');out body;'.format(
            lat=venue.get('location').get('lat'),
            lng=venue.get('location').get('lng'),
        )

    response = requests.post('https://overpass-api.de/api/interpreter', data=query)

    response.raise_for_status()

    osm = response.json()
    elements = osm.get('elements')

    def is_match(osm_obj):
        element_name = osm_obj.get('tags').get('name')
        distance = editdistance.eval(venue_name, element_name)
        edit_pct = (float(distance) / max(len(venue_name), len(element_name))) * 100.0

        # print "{} -- {} ({:0.1f}%)".format(venue_name, element_name, edit_pct)

        return edit_pct < 50

    potential_matches = filter(is_match, elements)

    if not potential_matches:
        user_email = user.get('contact', {}).get('email')
        print "No matches! Send an e-mail."
        message = """Hi {name},

You checked in at {venue_name} on Foursquare but that location doesn't seem to exist in OpenStreetMap. You should consider adding it near http://osm.org/?zoom=17&mlat={mlat}&mlon={mlon}!

-Checkin Checker
(Reply to this e-mail for feedback/questions. Uninstall at https://foursquare.com/settings/connections to stop these e-mails.)""".format(
            name=user.get('firstName', 'Friend'),
            venue_name=venue_name,
            mlat=round(venue.get('location').get('lat'), 6),
            mlon=round(venue.get('location').get('lng'), 6),
            email=user_email,
        )
        if user_email:
            send_email(user_email, "Your Recent Foursquare Checkin Isn't On OpenStreetMap", message)
    else:
        print "Matches: {}".format(', '.join(map(lambda i: i.get('tags').get('name'), potential_matches)))

    return 'OK'

if __name__ == '__main__':
    application.run()
