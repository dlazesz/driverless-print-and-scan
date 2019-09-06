#!/usr/bin/python3
# -*- coding: utf-8, vim: expandtab:ts=4 -*-

import os
import re
import threading
import subprocess

from flask import Flask, request
from flask_restful import Resource, Api
from werkzeug import secure_filename

UPLOAD_FOLDER = '/tmp/'
ALLOWED_EXTENSIONS = {'pdf'}

lp = False
if lp:
    # lp options. May need to be customized for your printer!
    PRINTER = 'default'  # Printer name from lpstat -p -d or 'default' for the system's default printer
    DUPLEX_OPTIONS = {'none': '', 'long': '-o sides=two-sided-long-edge', 'short': '-o sides=two-sided-short-edge'}
    ORIENTATION = {'portrait': '-o orientation-requested=3', 'landscape': '-o orientation-requested=4'}
else:
    # ipp options. May need to be customized for your printer!
    PRINTER = '192.168.x.x'  # Printer ip or DNS eg. 192.168.x.x if ipp://192.168.x.x/ipp/print is the IPP URL
    DUPLEX_OPTIONS = {'none': 'one-sided', 'long': 'two-sided-long-edge', 'short': 'two-sided-short-edge'}
    ORIENTATION = {'portrait': '3', 'landscape': '4'}


RANGE_RE = re.compile('([0-9]+(-[0-9]+)?)(,([0-9]+(-[0-9]+)?))*$')

# lock to control access to variable
print_lock = threading.Lock()


app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024
api = Api(app)

print_upload_form = """
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


def print_lp(duplex, page_range, orientation, copies, pdf, pdf_filename):
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

    pdf_path = os.path.join(app.config['UPLOAD_FOLDER'], pdf_filename)
    command.append(pdf_path)

    pdf.save(pdf_path)
    ret = subprocess.run(command, stderr=subprocess.PIPE)
    os.remove(pdf_path)

    if ret.returncode != 0:
        err_msg = ret.stderr.decode('UTF-8').rstrip()
        return 'Printing error: {0}'.format(err_msg), 500
    return None


def print_ipp(printer_address, duplex, page_range, orientation, copies, pdf, pdf_filename):
    printer_uri = 'ipp://{0}/ipp/print'.format(printer_address)

    page_ranges = ''
    if len(page_range) > 0:
        page_ranges = 'ATTR rangeOfInteger page-ranges {0}'.format(page_range)

    pdf_path = os.path.join(app.config['UPLOAD_FOLDER'], pdf_filename)
    print_job_config = """{{
    # Copied from: https://raw.githubusercontent.com/istopwg/ippsample/master/examples/create-job.test
    NAME "Create a job with REST API"

    OPERATION Create-Job

    GROUP operation-attributes-tag
        ATTR charset attributes-charset utf-8
        ATTR language attributes-natural-language en
        ATTR uri printer-uri $uri
        ATTR name requesting-user-name $user

    GROUP job-attributes-tag
        ATTR integer copies {0}
        ATTR keyword sides {1}
        {2}
        ATTR enum orientation-requested {4}

    STATUS successful-ok

    EXPECT job-id
    EXPECT job-uri

}}

{{

    NAME "Print a PDF with REST API"

    OPERATION Send-Document

    GROUP operation-attributes-tag
        ATTR charset attributes-charset utf-8
        ATTR language attributes-natural-language en
        ATTR uri printer-uri $uri
        ATTR integer job-id $job-id
        ATTR name requesting-user-name $user
        ATTR boolean last-document true

    FILE {3}


    # What statuses are OK?
    STATUS successful-ok

}}
""".format(copies, DUPLEX_OPTIONS[duplex], page_ranges, pdf_path, ORIENTATION[orientation])

    config_file = os.path.join(app.config['UPLOAD_FOLDER'], '{0}.config'.format(pdf_filename))
    fh = open(config_file, 'w', encoding='UTF-8')
    fh.write(print_job_config)
    fh.close()
    pdf.save(pdf_path)
    ret = subprocess.run(['ipptool', printer_uri, config_file, '-f', pdf_path], stderr=subprocess.PIPE)
    os.remove(pdf_path)
    os.remove(config_file)
    if ret.returncode != 0:
        err_msg = ret.stderr.decode('UTF-8').rstrip()
        return 'Printing error: {0}'.format(err_msg), 500
    return None


class PrintREST(Resource):
    @staticmethod
    @app.route('/print')
    def usage():
        return print_upload_form

    @staticmethod
    @app.route('/print', methods=['POST'])
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
            with print_lock:
                if lp:
                    ret = print_lp(duplex, page_range, orientation, copies, pdf, pdf_filename)
                else:
                    ret = print_ipp(PRINTER, duplex, page_range, orientation, copies, pdf, pdf_filename)
            if ret is not None:
                return ret

            return 'Printing "{0}" to "{1}" with duplex "{2}" range "{3}" in "{4}" orientation {5} times...'.format(
                pdf_filename, PRINTER, duplex, page_range, orientation, copies)
        return 'Some parameters wrong: {0} {1}'.format(duplex, pdf.filename), 400


if __name__ == '__main__':
    app.run(debug=False)
