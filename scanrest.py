#!/usr/bin/python3
# -*- coding: utf-8, vim: expandtab:ts=4 -*-

import threading
from io import BytesIO
from xml.etree import ElementTree
from json import dumps

from flask import Flask, request, send_file
from flask_restful import Resource, Api

from requests import get as requests_get, post as requests_post

# To be edited...
SCANNER_IP = '192.168.X.X'
ALLOW_MAX_A4_SIZE = False


class ESCLScanner:
    a4_width_px_300dpi = 2480
    a4_height_px_300dpi = 3508

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
      <pwg:InputSource>{3}</pwg:InputSource>
      <scan:ColorMode>{4}</scan:ColorMode>
      <scan:XResolution>{5}</scan:XResolution>
      <scan:YResolution>{5}</scan:YResolution>
      <pwg:DocumentFormat>{6}</pwg:DocumentFormat>
      <scan:Intent>{7}</scan:Intent>
    </scan:ScanSettings>"""

    @staticmethod
    def _get_range(inp_caps, namespaces):
        """
        A4 (210mm x 297mm) 2480px x 3508px @300DPI
        The latter format is returned. Must compute other sizes for other DPIs!
        """
        min_width = int(inp_caps.find('./scan:MinWidth', namespaces).text)
        max_width = int(inp_caps.find('./scan:MaxWidth', namespaces).text)
        min_height = int(inp_caps.find('./scan:MinHeight', namespaces).text)
        max_height = int(inp_caps.find('./scan:MaxHeight', namespaces).text)

        if ALLOW_MAX_A4_SIZE:
            max_width = min(max_width, ESCLScanner.a4_width_px_300dpi)
            max_height = min(max_height, ESCLScanner.a4_height_px_300dpi)

        width_range = range(min_width, max_width+1)
        height_range = range(min_height, max_height + 1)
        return width_range, height_range

    @staticmethod
    def _get_resolutions(inp_caps, namespaces):
        x_resolutions = [int(e.text)
                         for e in inp_caps.findall('./scan:SettingProfiles/'
                                                   'scan:SettingProfile/scan:SupportedResolutions/'
                                                   'scan:DiscreteResolutions/scan:DiscreteResolution/'
                                                   'scan:XResolution', namespaces)]
        y_resolutions = [int(e.text)
                         for e in inp_caps.findall('./scan:SettingProfiles/'
                                                   'scan:SettingProfile/scan:SupportedResolutions/'
                                                   'scan:DiscreteResolutions/scan:DiscreteResolution/'
                                                   'scan:YResolution', namespaces)]
        return sorted((min(x, y) for x, y in zip(x_resolutions, y_resolutions)), reverse=True)

    @staticmethod
    def _get_max_optical_resolution(inp_caps, namespaces):
        x_max_optical_resolution = int(inp_caps.find('./scan:MaxOpticalXResolution', namespaces).text)
        y_max_optical_resolution = int(inp_caps.find('./scan:MaxOpticalYResolution', namespaces).text)
        return min(x_max_optical_resolution, y_max_optical_resolution)

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

        caps = {}
        for source_name1, source_name2, source_name3 in \
                (('Platen', 'Platen', 'Platen'), ('Adf', 'AdfSimplex', 'Feeder')):
            inp_caps = scanner_cap_tree.find('./scan:{0}/scan:{1}InputCaps'.format(source_name1, source_name2),
                                             namespaces)

            width_range, height_range = ESCLScanner._get_range(inp_caps, namespaces)

            formats = [ESCLScanner.mime_to_format[e.text]
                       for e in inp_caps.findall('./scan:SettingProfiles/scan:SettingProfile/scan:DocumentFormats/'
                                                 'pwg:DocumentFormat', namespaces)]

            color_modes = sorted((ESCLScanner.color_modes_to_name[e.text]
                                  for e in inp_caps.findall('./scan:SettingProfiles/scan:SettingProfile/'
                                                            'scan:ColorModes/scan:ColorMode',
                                                            namespaces)), reverse=True)

            resolutions = ESCLScanner._get_resolutions(inp_caps, namespaces)

            # Comnpute pixel ranges for different DPIs (must be supplied in 300DPI to the scanner!)
            width_ranges = {}
            height_ranges = {}
            for res in resolutions:
                width_ranges[res] = range(width_range.start, (width_range.stop-1)*res//300+1)
                height_ranges[res] = range(height_range.start, (height_range.stop-1)*res//300+1)

            supported_intents = [e.text for e in inp_caps.findall('./scan:SupportedIntents/scan:Intent', namespaces)]

            max_optical_resolution = ESCLScanner._get_max_optical_resolution(inp_caps, namespaces)

            caps[source_name3] = {'width': width_ranges, 'height': height_ranges, 'formats': formats,
                                  'colormodes': color_modes, 'resolutions': resolutions, 'intents': supported_intents,
                                  'max_optical_resolution': max_optical_resolution}

        return status, {'version': escl_version, 'makeandmodel': make_and_model, 'serialnumber': serial_number,
                        'caps_by_source': caps}

    @staticmethod
    def _put_together_query(caps, input_source, height, width, color_mode, resolution, image_format, intent):
        version = caps['version']
        if input_source not in caps['caps_by_source']:
            raise ValueError('Input source ({0}) is not in the available input sources ({1})!'.
                             format(input_source, caps['caps_by_source']))

        caps_for_curr_source = caps['caps_by_source'][input_source]

        if height is None:
            height = caps_for_curr_source['height'].get(resolution, 300).stop - 1
        if width is None:
            width = caps_for_curr_source['width'].get(resolution, 300).stop - 1

        checks = [(resolution, caps_for_curr_source['resolutions'], 'Resoluton', 'resolutons'),
                  (height, caps_for_curr_source['height'][resolution], 'Height', 'range'),
                  (width, caps_for_curr_source['width'][resolution], 'Width', 'range'),
                  (color_mode, ESCLScanner.name_to_color_modes.keys(), 'Color mode', 'modes'),
                  (image_format, ESCLScanner.format_to_mime.keys(), 'Format', 'formats'),
                  (intent, caps_for_curr_source['intents'], 'Intent', 'intents'),
                  ]
        for value, good_values, name, name_of_values in checks:
            if value not in good_values:
                raise ValueError('{0} ({1}) is not in {2} ({3})!'.format(name, value, name_of_values, good_values))

        # Scale the height and width to 300DPI for the XML
        height = height*300//resolution
        width = width*300//resolution

        return ESCLScanner.query_xml.format(version, height, width, input_source,
                                            ESCLScanner.name_to_color_modes[color_mode], resolution,
                                            ESCLScanner.format_to_mime[image_format], intent)

    @staticmethod
    def _post_xml(scanner_ip, xml):
        resp = requests_post('http://{0}/eSCL/ScanJobs'.format(scanner_ip), data=xml,
                             headers={'Content-Type': 'text/xml'})
        if resp.status_code == 201:
            return '{0}/NextDocument'.format(resp.headers['Location']), 201
        return resp.reason, resp.status_code

    @staticmethod
    def scan(scanner_ip, input_source, height, width, color_mode, resolution, image_format, intent):
        status, caps = ESCLScanner.get_capabilities(scanner_ip)
        if status != 'Idle':
            ValueError('Scanner Status is not Idle: {0}'.format(status))
        try:
            xml = ESCLScanner._put_together_query(caps, input_source, height, width, color_mode, resolution,
                                                  image_format, intent)
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
<script>
// Globals
var caps = 'JSON_PLACEHOLDER';
var capsJson = JSON.parse(caps)["caps_by_source"];

function makeRadioButton(name, value, checked) {
    // From: https://stackoverflow.com/questions/23430455/
    //       in-html-with-javascript-create-new-radio-button-and-its-text/23430717#23430717

    var label = document.createElement("label");
    var radio = document.createElement("input");
    radio.type = "radio";
    radio.name = name;
    radio.value = value;
    radio.checked = checked

    label.appendChild(radio);
    label.appendChild(document.createTextNode(value));

    return label;
}

function placeRadioButtons(name, text, propValues) {
    var radioHome = document.getElementById(name);
    radioHome.innerHTML = "";
    radioHome.insertAdjacentHTML("afterbegin", text);
    var first = true;
    for (var prop in propValues[name]) {
        radioHome.appendChild(document.createElement("br"));
        radioHome.appendChild(makeRadioButton(name, propValues[name][prop], first));
        first = false;
    }
}

function refresh() {
    var x = document.getElementById("inputSource").value;
    if (x  in capsJson) {
        var capsInputSource = capsJson[x];
    }
    else {
        alert("Internal error: No such input source!");
        return false;
    }
    placeRadioButtons("colormodes", "Color Mode:", capsInputSource);
    placeRadioButtons("resolutions", "Resolution:", capsInputSource);

    // Adjust height and width to resolution
    var x = document.getElementsByName("resolutions");
    for (var i = 0; i < x.length; i++) {
        if (x[i].type == "radio") {
            x[i].addEventListener("change", function() {
                document.getElementById("height").placeholder = capsInputSource["height"][this.value];
                document.getElementById("width").placeholder = capsInputSource["width"][this.value];
            });
        }
        if (i == 0) {
            document.getElementById("height").placeholder = capsInputSource["height"][x[i].value];
            document.getElementById("width").placeholder = capsInputSource["width"][x[i].value];
        }
    }

    placeRadioButtons("formats", "Image Format:", capsInputSource);
    placeRadioButtons("intents", "Intent:", capsInputSource);
}

function onload() {
    var sources = document.getElementById("inputSource");
    for (var source in capsJson) {
        var opt = document.createElement("option");
        opt.value = source;
        opt.text = source;
        sources.appendChild(opt);
    }
    refresh();
}

</script>
</head>
<body onload="onload()">

<form action="" method="post">
    <p>
        Input Source: <br/>
        <select id="inputSource" name="inputSource" onchange="refresh()">
        </select>
    </p>
    <p>
        Height x Width: <br/>
        <input id="height" type="number" name="height" placeholder=0> x
        <input id="width" type="number" name="width"  placeholder=0>
    </p>
    <p id="colormodes">
    </p>
    <p id="resolutions">
    </p>
    <p id="formats">
    </p>
    <p id="intents">
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
    @app.route('/scan')
    def usage():
        status, scanner_caps = ESCLScanner.get_capabilities(SCANNER_IP)
        if status != 'Idle':
            return 'Status is not "Idle" ({0})!'.format(status), 500

        # Replace ranges with maximum values
        for source in scanner_caps['caps_by_source'].keys():
            for res in scanner_caps['caps_by_source'][source]['height'].keys():
                scanner_caps['caps_by_source'][source]['height'][res] = \
                    scanner_caps['caps_by_source'][source]['height'][res].stop - 1
                scanner_caps['caps_by_source'][source]['width'][res] = \
                    scanner_caps['caps_by_source'][source]['width'][res].stop - 1
        json = dumps(scanner_caps)
        return scan_settings_form.replace('JSON_PLACEHOLDER', json)

    @staticmethod
    @app.route('/scan', methods=['POST'])
    def scan():
        input_source = request.form['inputSource']
        height = request.form['height']
        width = request.form['width']
        color_mode = request.form['colormodes']
        resolution = request.form['resolutions']
        image_format = request.form['formats']
        intent = request.form['intents']

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

        msg, status = ESCLScanner.scan(SCANNER_IP, input_source, height, width, color_mode, resolution, image_format,
                                       intent)
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
