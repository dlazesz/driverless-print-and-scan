# Driverless Printing and Scanning REST API

A simple REST API for scanning (eSCL) to JPEG or PDF and printing (with IPP or CUPS) a PDF from anywhere (eg. via a webbrowser) with ease

## Motivation

I could not find a simple web app running on a server that could initiate a printing and scanning process from other machines without installing anything on the client machines.
So I had to write my own on top of almost 10 years old standards (IPP and eSCL)... Et voilà!

Motto:
 > "So tonight I'm gonna print and scan like it's nineteen ninety-nine!" (refering to Prince)

## Requirements

- Python 3
- A server (`ipptool` in PATH or CUPS with the printer driver properly installed)
- An IPP capable printer and/or an eSCL capable scanner
- A WSGI server

## Example setup

1. Setup your printer in CUPS on the server (if the CUPS option is chosen)
2. Make a virtual environment: `sudo virtualenv -p python3 /var/www/driverless_print_and_scan_venv`
3. Clone the repository: `sudo git clone https://github.com/dlazesz/driverless_print_and_scan_venv/driverless-print-and-scan`
4. Modify the `PRINTER` variable in `printrest.py` to the appropriate name and `SCANNER_IP` variable in `scanrest.py`
5. Install requirements in the virtual environment `source /var/www/driverless_print_and_scan_venv/bin/activate; pip install -r requirements.txt`
6. Set user permissions: `sudo chown -R user:www-data /var/www/driverless_print_and_scan_venv`
7. Create the WSGI file:
    ```python
   from printrest import app

   if __name__ == '__main__':
        app.run()
    ```
8. Setup a WSGI server. I do not recommend _uwsgi_ because of [its numerous quirks](https://uwsgi-docs.readthedocs.io/en/latest/ThingsToKnow.html)
    - Example in _apache_:
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
    - Example in _Gunicorn_ + _Nginx_ + _Systemd_:
        - Create Systemd unit `sudo mcedit /etc/systemd/system/printREST.service` with the following content:
            ```ini
            [Unit]
            Description=Gunicorn instance to serve printREST
            After=network.target
            
            [Service]
            User=sammy
            Group=www-data
            WorkingDirectory=/var/www/driverless_print_and_scan_venv/driverless-print-and-scan
            Environment="PATH=/var/www/driverless_print_and_scan_venv/bin"
            ExecStart=/var/www/driverless_print_and_scan_venv/bin/gunicorn --workers 2 --bind unix:printREST.sock -m 007 wsgi:app
            
            [Install]
            WantedBy=multi-user.target
            ```
        - Start and enable the _Systemd_ service `sudo systemctl start printREST && sudo systemctl enable printREST`
        - Add location to _Nginx_:
            ```
            location /print {
                # Do not forget to add password protection!
                include proxy_params;
                proxy_pass http://unix:/var/www/driverless_print_and_scan_venv/driverless-print-and-scan/printREST.sock;
                client_max_body_size 100M;  # 1MB is the default upload limit! 
            }
            ```
        - Restart _Nginx_ `sudo systemctl restart nginx`
5. Navigate to http://yourserver.com/print
6. Print from anywhere to your printer without installing drivers
7. Profit!

The same goes for the scanner setup

## License

This program is licensed under the LGPL 3.0 license.
