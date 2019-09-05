# pdf-rest-print

A simple REST API for printing PDF to printers (with IPP or CUPS) from anywhere with ease

## Motivation

I could not find a simple web app running on a server with the printer driver installed that could initiate a printing process from anywhere without installing anything on the client machine. So I had to write my own... Et voilà!

## Requirements

- Python 3
- An IPP capable printer or a server with CUPS with the printer driver properly installed
- A WSGI server

## Usage

1. Setup your printer in CUPS on the server
2. (Optional) Modify the `PRINTER` variable in `printrest.py` to the appropriate name
3. Setup a virtualenv, clone the repository and install the requirements in `requirements.txt`
4. Setup a WSGI server. For example in _apache_:
    ```xml
            <VirtualHost *:80>

                WSGIDaemonProcess printrest threads=5 python-path=/var/www/printrest_venv/lib/python3.5/site-packages
                WSGIScriptAlias /print /var/www/printrest_venv/printREST/print.wsgi

                <Directory /var/www/printrest_venv/printREST>
                    WSGIProcessGroup printrest
                    WSGIApplicationGroup %{GLOBAL}
                    Order deny,allow
                    Allow from all
                </Directory>
            </VirtualHost>
    ```

5. Navigate to http://yourserver.com/print
6. Print from anywhere to your printer without installing drivers

## License

This program is licensed under the LGPL 3.0 license.
