import os
from vmp_util import Application, SL_Logging

#get cert file for VVM communications
def where():
    app_data_path = Application.app_data_path()
    cert_path = os.path.join(app_data_path, 'ca-bundle.crt')
    if not os.path.exists(cert_path):
        log = SL_Logging.getLogger("vmp-certifi")
        log.error("No certificate bundle found at '%s'", cert_path)
    return cert_path
