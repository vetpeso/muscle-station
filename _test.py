import requests, sys
sys.stdout.reconfigure(encoding='utf-8')
s = requests.Session()
s.post('https://muscle-station-production.up.railway.app/login', data={'username':'admin','password':'admin123'}, allow_redirects=False)
r = s.get('https://muscle-station-production.up.railway.app/appointments')
html = r.text
print('has setCallStatus:', 'setCallStatus' in html)
print('onclick count:', html.count('onclick="setCallStatus'))
print('has call-group:', html.count('class="call-group'))
print('has fetch:', 'fetch(' in html)
print('has fetch API endpoint:', '/toggle_call/' in html)

# Check if the buttons might be behind the sidebar on mobile
# Look for position z-index issues
print('call-group count:', html.count('call-group'))
print('has call-answered:', 'call-answered' in html)
print('has call-not-answered:', 'call-not-answered' in html)
