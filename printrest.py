#!/usr/bin/python3
# -*- coding: utf-8, vim: expandtab:ts=4 -*-

import os
import re
import threading
import subprocess

from flask import Flask, request
from flask_restful import Resource, Api
from werkzeug import secure_filename

PRINTER = 'default'  # Printer name from lpstat -p -d or 'default' for the system's default printer
UPLOAD_FOLDER = '/tmp/'
ALLOWED_EXTENSIONS = {'pdf'}

DUPLEX_OPTIONS = {'none': '', 'long': '-o sides=two-sided-long-edge', 'short': '-o sides=two-sided-short-edge'}
ORIENTATION = {'portrait': '-o orientation-requested=3', 'landscape': '-o orientation-requested=4'}
RANGE_RE = re.compile('([0-9]+(-[0-9]+)?)(,([0-9]+(-[0-9]+)?))*$')

# lock to control access to variable
print_lock = threading.Lock()


app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024
api = Api(app)

upload_form = """
<!DOCTYPE html>
<html>
<head>
<style>
body, html {

    width: 100%;
    height: 100%;
    margin: 0;
    padding: 0;
    display:table;
}
body {
    display:table-cell;
    vertical-align:middle;
}
form {
    display:table;/* shrinks to fit conntent */
    margin:auto;
}
</style>
</head>
<body>

<form action="" method="post" enctype="multipart/form-data">
    <p>
        Upload PDF to print: <br/>
        <input type="file" name="uploadedPDF" accept=".pdf">
    </p>
    <p>
        Duplex: <br/>
        <input type="radio" name="duplex" value="long" checked> Long edge flipped<br>
        <input type="radio" name="duplex" value="short"> Short edge flipped<br>
        <input type="radio" name="duplex" value="none"> Single Page
    </p>
    <p>
       Range: <br/>
       <input type="text" name="range" placeholder="1-5,8,11-13">
    </p>
    <p>
        Orientation: <br/>
        <input type="radio" name="orientation" value="portrait" checked> Portrait<br>
        <input type="radio" name="orientation" value="landscape"> Landscape<br>
    </p>
    <p>
       Copies: <br/>
       <input type="number" name="copies" placeholder="1">
    </p>
    <p>
        <input type="submit" value="Print" name="submit">
    </p>
</form>

</body>
</html>
"""


class PrintREST(Resource):
    @staticmethod
    @app.route('/')
    def usage():
        return upload_form

    @staticmethod
    @app.route('/', methods=['POST'])
    def print():
        pdf = request.files['uploadedPDF']
        pdf_filename = secure_filename(pdf.filename)

        duplex = request.form['duplex']
        page_range = request.form['range']
        orientation = request.form['orientation']
        copies = request.form['copies']
        if copies == '':
            copies = 1
        else:
            copies = int(copies)

        if duplex in DUPLEX_OPTIONS and \
                pdf and pdf.filename.rsplit('.', 1)[1] in ALLOWED_EXTENSIONS and \
                (len(page_range) == 0 or RANGE_RE.match(page_range)) and \
                orientation in ORIENTATION and \
                copies > 0:

            command = ['lp']

            if PRINTER != 'default':
                command.extend(['-d', PRINTER])

            if duplex != 'none':
                command.extend(DUPLEX_OPTIONS[duplex].split())

            if len(page_range) > 0:
                command.extend(['-o', 'page-ranges=' + page_range])

            command.extend(ORIENTATION[orientation].split())

            if copies > 1:
                command.extend(['-n', str(copies)])

            with print_lock:
                pdf_path = os.path.join(app.config['UPLOAD_FOLDER'], pdf_filename)
                command.append(pdf_path)

                pdf.save(pdf_path)
                ret = subprocess.run(command, stderr=subprocess.PIPE)
                os.remove(pdf_path)

                if ret.returncode != 0:
                    err_msg = ret.stderr.decode('UTF-8').rstrip()
                    return 'Printing error: {0}'.format(err_msg), 500

            return 'Printing "{0}" to "{1}" with duplex "{2}" range "{3}" in "{4}" orientation {5} times...'.format(
                pdf_filename, PRINTER, duplex, page_range, orientation, copies)
        return 'Some parameters wrong: {0} {1}'.format(duplex, pdf.filename), 400


if __name__ == '__main__':
    app.run(debug=False)
