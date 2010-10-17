# GOOGLE APP ENGINE IMPORTS
from google.appengine.ext import webapp
from google.appengine.ext.webapp.util import run_wsgi_app
from google.appengine.api import urlfetch

# PYTHON IMPORTS
import logging
from StringIO import StringIO
import struct
import rfc822
import datetime
import time

# CONSTANTS
PROD_DOMAIN = '9folds.s3.amazonaws.com'
DEV_DOMAIN = '9foldsdev.s3.amazonaws.com'

def getImageInfo(data):
    data = str(data)
    size = len(data)
    height = -1
    width = -1
    content_type = ''

    # handle GIFs
    if (size >= 10) and data[:6] in ('GIF87a', 'GIF89a'):
        # Check to see if content_type is correct
        content_type = 'image/gif'
        w, h = struct.unpack("<HH", data[6:10])
        width = int(w)
        height = int(h)

    # See PNG 2. Edition spec (http://www.w3.org/TR/PNG/)
    # Bytes 0-7 are below, 4-byte chunk length, then 'IHDR'
    # and finally the 4-byte width, height
    elif ((size >= 24) and data.startswith('\211PNG\r\n\032\n')
          and (data[12:16] == 'IHDR')):
        content_type = 'image/png'
        w, h = struct.unpack(">LL", data[16:24])
        width = int(w)
        height = int(h)

    # Maybe this is for an older PNG version.
    elif (size >= 16) and data.startswith('\211PNG\r\n\032\n'):
        # Check to see if we have the right content type
        content_type = 'image/png'
        w, h = struct.unpack(">LL", data[8:16])
        width = int(w)
        height = int(h)

    # handle JPEGs
    elif (size >= 2) and data.startswith('\377\330'):
        content_type = 'image/jpeg'
        jpeg = StringIO(data)
        jpeg.read(2)
        b = jpeg.read(1)
        try:
            while (b and ord(b) != 0xDA):
                while (ord(b) != 0xFF): b = jpeg.read
                while (ord(b) == 0xFF): b = jpeg.read(1)
                if (ord(b) >= 0xC0 and ord(b) <= 0xC3):
                    jpeg.read(3)
                    h, w = struct.unpack(">HH", jpeg.read(4))
                    break
                else:
                    jpeg.read(int(struct.unpack(">H", jpeg.read(2))[0])-2)
                b = jpeg.read(1)
            width = int(w)
            height = int(h)
        except struct.error:
            pass
        except ValueError:
            pass

    return content_type, width, height

def generate_thumbnail(file, t_width=125, t_height=125, x=None, y=None, x2=None, y2=None):
    logging.info('generate_thumb %sx%s' % (t_width, t_height))
    from google.appengine.api import images
    type,width,height = getImageInfo(file)

    file = images.Image(file)
    if x and y and x2 and y2:
        left_x, top_y, right_x, bottom_y = x/width, y/height, x2/width, y2/height
        file.crop(left_x, top_y, right_x, bottom_y)
        cropped = True
    else:
        cropped = False

    # First let's resize if the image is wider then the target aspect ratio of the thumbnail
    if((not t_height) or float(width)/height<t_width/t_height):
        file.resize(width=int(t_width))
    else:
        file.resize(height=int(t_height))
    file = file.execute_transforms(output_encoding=images.JPEG)

    type,width,height = getImageInfo(file)
    width = float(width)
    height = float(height)

    # CROP to the target aspect ratio
    if not cropped and t_height and t_width:
        cropoff_width = cropoff_height = 0.0
        if(width/height>t_width/t_height):
            cropoff_width = (width-t_width/t_height*height)/width/2
            logging.info('regular crop width. cropoff_width [%f] width/height [%f] t_width/t_height [%f] width [%d] height [%d]' % (cropoff_width, width/height, t_width/t_height, width, height))
        else:
            cropoff_height = (height - t_height/t_width*width)/height/2
            logging.info('regular crop height. cropoff_height [%f] width/height [%f] t_width/t_height [%f] width [%d] height [%d]' % (cropoff_height, width/height, t_width/t_height, width, height))

        file = images.Image(file)
        file.crop(
                           top_y=cropoff_height,
                           bottom_y=1.0 - cropoff_height,
                           left_x=cropoff_width,
                           right_x=1.0-cropoff_width)
        file = file.execute_transforms(output_encoding=images.JPEG)

    return file

class MainPage(webapp.RequestHandler):
    def get(self, thumb_data, url_path):
        self.response.headers['Cache-Control']  = 'public, max-age=31553600' # One Year
        self.response.headers['Expires']  = rfc822.formatdate(time.mktime((datetime.datetime.now() + datetime.timedelta(360)).timetuple()))
        self.response.headers['Content-Type'] = "image/jpeg"
        if 'If-Modified-Since' in self.request.headers or 'If-None-Match' in self.request.headers:
            self.response.set_status(304)
            return

        domain = self.request.get('domain', PROD_DOMAIN)
        if domain!= PROD_DOMAIN and domain!= DEV_DOMAIN:
            self.response.out.write('Bad Request. Invalid domain %s' % domain)
            self.response.set_status(400)
            return

        thumb_data = thumb_data.split('x')
        thumb_data = [float(i) for i in thumb_data]

        url = 'http://%s/%s' % (domain, url_path)
        logging.info('retrieving %s' % url)
        response = urlfetch.fetch(url=url)
        # Error handling
        if response.status_code!=200:
            self.response.headers = response.headers
            self.response.out.write(response.content)
            self.response.set_status(response.status_code)
            return

        thumb = response.content
        self.response.headers['ETag'] = '"%s"' % (url_path,)
        self.response.headers['Cache-Control']  = 'public, max-age=31536000' # One Year
        thumb = generate_thumbnail(thumb, *thumb_data)
        self.response.out.write(thumb)

application = webapp.WSGIApplication(
                                     [('/([^\/]*)/(.*)', MainPage)],
                                     debug=True)

def main():
    run_wsgi_app(application)

if __name__ == "__main__":
    main()