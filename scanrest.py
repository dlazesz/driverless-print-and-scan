#!/usr/bin/python3
# -*- coding: utf-8, vim: expandtab:ts=4 -*-

import threading
from io import BytesIO
from xml.etree import ElementTree

from flask import Flask, request, send_file
from flask_restful import Resource, Api

from requests import get as requests_get, post as requests_post

# To be edited...
SCANNER_IP = '192.168.X.X'


class ESCLScanner:
    # These are scanner dependent values...
    format_to_mime = {'PDF': 'application/pdf', 'JPEG': 'image/jpeg'}
    name_to_color_modes = {'BackAndWhite': 'BlackAndWhite1', 'Grayscale': 'Grayscale8', 'Color': 'RGB24'}

    namespaces = {'pwg': 'http://www.pwg.org/schemas/2010/12/sm',
                  'scan': 'http://schemas.hp.com/imaging/escl/2011/05/03'}
    mime_to_format = {v: k for k, v in format_to_mime.items()}
    color_modes_to_name = {v: k for k, v in name_to_color_modes.items()}

    query_xml = """<?xml version="1.0" encoding="UTF-8"?>
    <scan:ScanSettings xmlns:pwg="http://www.pwg.org/schemas/2010/12/sm" 
                       xmlns:scan="http://schemas.hp.com/imaging/escl/2011/05/03">
      <pwg:Version>{0}</pwg:Version>
      <pwg:ScanRegions>
        <pwg:ScanRegion>
          <pwg:Height>{1}</pwg:Height>
          <pwg:Width>{2}</pwg:Width>
          <pwg:XOffset>0</pwg:XOffset>
          <pwg:YOffset>0</pwg:YOffset>
        </pwg:ScanRegion>
      </pwg:ScanRegions>
      <pwg:InputSource>Platen</pwg:InputSource>
      <scan:ColorMode>{3}</scan:ColorMode>
      <scan:XResolution>{4}</scan:XResolution>
      <scan:YResolution>{4}</scan:YResolution>
      <pwg:DocumentFormat>{5}</pwg:DocumentFormat>
      <scan:Intent>{6}</scan:Intent>
    </scan:ScanSettings>"""

    @staticmethod
    def get_capabilities(scanner_ip):
        namespaces = ESCLScanner.namespaces

        # .content == .text in bytes
        scanner_status_xml = requests_get('http://{0}/eSCL/ScannerStatus'.format(scanner_ip)).content
        scanner_status_tree = ElementTree.fromstring(scanner_status_xml)
        status = scanner_status_tree.find('./pwg:State', namespaces).text

        # .content == .text in bytes
        scanner_cap_xml = requests_get('http://{0}/eSCL/ScannerCapabilities'.format(scanner_ip)).content
        scanner_cap_tree = ElementTree.fromstring(scanner_cap_xml)
        escl_version = scanner_cap_tree.find('./pwg:Version', namespaces).text
        make_and_model = scanner_cap_tree.find('./pwg:MakeAndModel', namespaces).text
        serial_number = scanner_cap_tree.find('./pwg:SerialNumber', namespaces).text

        min_width = int(scanner_cap_tree.find('./scan:Platen/scan:PlatenInputCaps/scan:MinWidth', namespaces).text)
        max_width = int(scanner_cap_tree.find('./scan:Platen/scan:PlatenInputCaps/scan:MaxWidth', namespaces).text)
        min_height = int(scanner_cap_tree.find('./scan:Platen/scan:PlatenInputCaps/scan:MinHeight', namespaces).text)
        max_height = int(scanner_cap_tree.find('./scan:Platen/scan:PlatenInputCaps/scan:MaxHeight', namespaces).text)
        width_range = range(min_width, max_width+1)
        height_range = range(min_height, max_height + 1)

        formats = [ESCLScanner.mime_to_format[e.text]
                   for e in scanner_cap_tree.findall('./scan:Platen/scan:PlatenInputCaps/scan:SettingProfiles/'
                                                     'scan:SettingProfile/scan:DocumentFormats/pwg:DocumentFormat',
                                                     namespaces)]

        color_modes = sorted((ESCLScanner.color_modes_to_name[e.text]
                              for e in scanner_cap_tree.findall('./scan:Platen/scan:PlatenInputCaps/'
                                                                'scan:SettingProfiles/scan:SettingProfile/'
                                                                'scan:ColorModes/scan:ColorMode',
                                                                namespaces)), reverse=True)

        x_resolutions = [int(e.text)
                         for e in scanner_cap_tree.findall('./scan:Platen/scan:PlatenInputCaps/scan:SettingProfiles/'
                                                           'scan:SettingProfile/scan:SupportedResolutions/'
                                                           'scan:DiscreteResolutions/scan:DiscreteResolution/'
                                                           'scan:XResolution', namespaces)]
        y_resolutions = [int(e.text)
                         for e in scanner_cap_tree.findall('./scan:Platen/scan:PlatenInputCaps/scan:SettingProfiles/'
                                                           'scan:SettingProfile/scan:SupportedResolutions/'
                                                           'scan:DiscreteResolutions/scan:DiscreteResolution/'
                                                           'scan:YResolution', namespaces)]
        resolutions = sorted((min(x, y) for x, y in zip(x_resolutions, y_resolutions)), reverse=True)

        supported_intents = [e.text
                             for e in scanner_cap_tree.findall('./scan:Platen/scan:PlatenInputCaps/'
                                                               'scan:SupportedIntents/scan:Intent', namespaces)]

        x_max_optical_resolution = int(scanner_cap_tree.find('./scan:Platen/scan:PlatenInputCaps/'
                                                             'scan:MaxOpticalXResolution',
                                                             namespaces).text)
        y_max_optical_resolution = int(scanner_cap_tree.find('./scan:Platen/scan:PlatenInputCaps/'
                                                             'scan:MaxOpticalYResolution',
                                                             namespaces).text)
        max_optical_resolution = min(x_max_optical_resolution, y_max_optical_resolution)

        return status, {'version': escl_version, 'makeandmodel': make_and_model, 'serialnumber': serial_number,
                        'width': width_range, 'height': height_range, 'formats': formats, 'colormodes': color_modes,
                        'resolutions': resolutions, 'intents': supported_intents,
                        'max_optical_resolution': max_optical_resolution}

    @staticmethod
    def _put_together_query(caps, height, width, color_mode, resolution, image_format, intent):
        version = caps['version']
        if height is None:
            height = caps['height'].stop - 1
        if width is None:
            width = caps['width'].stop - 1

        checks = [(height, caps['height'], 'Height', 'range'),
                  (width, caps['width'], 'Width', 'range'),
                  (color_mode, ESCLScanner.name_to_color_modes.keys(), 'Color mode', 'modes'),
                  (resolution, caps['resolutions'], 'Resoluton', 'resolutons'),
                  (image_format, ESCLScanner.format_to_mime.keys(), 'Format', 'formats'),
                  (intent, caps['intents'], 'Intent', 'intents'),
                  ]
        for value, good_values, name, name_of_values in checks:
            if value not in good_values:
                raise ValueError('{0} ({1}) is not in {2} ({3})!'.format(name, value, name_of_values, good_values))

        return ESCLScanner.query_xml.format(version, height, width, ESCLScanner.name_to_color_modes[color_mode],
                                            resolution, ESCLScanner.format_to_mime[image_format], intent)

    @staticmethod
    def _post_xml(scanner_ip, xml):
        resp = requests_post('http://{0}/eSCL/ScanJobs'.format(scanner_ip), data=xml,
                             headers={'Content-Type': 'text/xml'})
        if resp.status_code == 201:
            '{0}/NextDocument'.format(resp.headers['Location'])
            return '{0}/NextDocument'.format(resp.headers['Location']), 201
        return resp.reason, resp.status_code

    @staticmethod
    def scan(scanner_ip, height, width, color_mode, resolution, image_format, intent):
        status, caps = ESCLScanner.get_capabilities(scanner_ip)
        if status != 'Idle':
            ValueError('Scanner Status is not Idle: {0}'.format(status))
        try:
            xml = ESCLScanner._put_together_query(caps, height, width, color_mode, resolution, image_format, intent)
        except ValueError as msg:
            return msg, 400
        return ESCLScanner._post_xml(scanner_ip, xml)


# lock to control access to variable
scan_lock = threading.Lock()

app = Flask(__name__)
api = Api(app)

scan_settings_form = """
<!DOCTYPE html>
<html>
<head>
<style>
body, html {{

    width: 100%;
    height: 100%;
    margin: 0;
    padding: 0;
    display:table;
}}
body {{
    display:table-cell;
    vertical-align:middle;
}}
form {{
    display:table;/* shrinks to fit conntent */
    margin:auto;
}}
</style>
</head>
<body>

<form action="" method="post">
    <p>
       Height x Width: <br/>
       <input type="number" name="height" placeholder="{0}"> x
       <input type="number" name="width" placeholder="{1}">
    </p>
    <p>
        Color mode: <br/>
{2}
    </p>
    <p>
       Resolution: <br/>
{3}
    </p>
    <p>
        Image format: <br/>
{4}
    </p>

    <p>
        Intent: <br/>
{5}
    </p>
    <p>
        <input type="submit" value="Scan" name="submit">
    </p>
</form>

</body>
</html>
"""


class ScanREST(Resource):
    @staticmethod
    def radio_helper(name, cap):
        if len(cap) > 0:
            for i, value in enumerate(cap):
                checked = ''
                if i == 0:
                    checked = 'checked'
                yield '       <input type="radio" name="{0}" value="{1}" {2}> {1}<br>\n'.format(name, value, checked)
        else:
            ValueError('No values for {0}!'.format(name))

    @staticmethod
    @app.route('/scan')
    def usage():
        status, scanner_caps = ESCLScanner.get_capabilities(SCANNER_IP)
        if status != 'Idle':
            return 'Status is not "idle" ({0})!'.format(status), 500

        max_height = scanner_caps['height'].stop-1
        max_width = scanner_caps['width'].stop-1
        color_modes = ''.join(radio for radio in ScanREST.radio_helper('color_mode', scanner_caps['colormodes']))
        resolutions = ''.join(radio for radio in ScanREST.radio_helper('resolution', scanner_caps['resolutions']))
        image_formats = ''.join(radio for radio in ScanREST.radio_helper('image_format', scanner_caps['formats']))
        intents = ''.join(radio for radio in ScanREST.radio_helper('intent', scanner_caps['intents']))

        return scan_settings_form.format(max_height, max_width, color_modes, resolutions, image_formats, intents)

    @staticmethod
    @app.route('/scan', methods=['POST'])
    def scan():
        height = request.form['height']
        width = request.form['width']
        color_mode = request.form['color_mode']
        resolution = request.form['resolution']
        image_format = request.form['image_format']
        intent = request.form['intent']

        try:
            if len(height) > 0:
                height = int(height)
            else:
                height = None
            if len(width) > 0:
                width = int(width)
            else:
                width = None
            resolution = int(resolution)
        except ValueError:
            return 'Values of {0} must be Integer instead of {1}!'.format('Height, Width and Resolution',
                                                                          ', '.join((height, width, resolution))), 400

        msg, status = ESCLScanner.scan(SCANNER_IP, height, width, color_mode, resolution, image_format, intent)
        if status == 201:
            response = requests_get(msg, stream=True)
            headers = dict(response.headers)
            mime = headers['Content-Type']
            name = '{0}.{1}'.format(headers['Content-Location'].split('/')[-1],
                                    ESCLScanner.mime_to_format[mime].lower())
            return send_file(BytesIO(response.content), mimetype=headers['Content-Type'], attachment_filename=name,
                             as_attachment=True)
        else:
            return 'Some parameters are wrong: {0}'.format(msg), status


if __name__ == '__main__':
    app.run(debug=False)
