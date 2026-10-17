"""Lets forms submit in the background and show the result in place (no page reload).

Routes keep doing what they always did: flash(...) and redirect(...). When the request comes from
static/js/ajax-forms.js (it sends the header "X-Requested-With: fetch"), that redirect is turned into
a small JSON answer instead:

    {"ok": true | false, "message": "<first flashed message>", "redirect": "<where the redirect pointed>"}

so the page can show the message right inside the form and keep everything as it is.
Normal browser form posts are not touched at all.
"""
from flask import jsonify, request, session


def register_ajax(app):
    @app.after_request
    def redirect_to_json(response):
        if request.headers.get('X-Requested-With') != 'fetch':
            return response

        location = response.headers.get('Location')
        if not (300 <= response.status_code < 400) or not location:
            return response

        flashes = session.get('_flashes') or []          # [[category, message], ...]
        errors = [message for category, message in flashes if category == 'error']
        ok = not errors
        if errors:
            message = errors[0]
        elif flashes:
            message = flashes[0][1]
        else:
            message = ''

        # A failure is shown in place, so its message must not appear again on the next page.
        # A success that is about to navigate keeps its message for the page that opens next.
        navigating = request.headers.get('X-Ajax-Navigate') == '1'
        if flashes and not (ok and navigating):
            session.pop('_flashes', None)

        reply = jsonify(ok=ok, message=message, redirect=location)
        reply.headers['Cache-Control'] = 'no-store'
        return reply