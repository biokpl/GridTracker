import base64
data = open(r'C:\Users\BioCSI\CLAUDE\GridTracker\2logo.png', 'rb').read()
b64  = base64.b64encode(data).decode('ascii')
svg  = (
    '<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
    'viewBox="0 0 128 128" width="128" height="128">\n'
    f'  <image href="data:image/png;base64,{b64}" width="128" height="128"/>\n'
    '</svg>'
)
open(r'C:\Users\BioCSI\CLAUDE\GridTracker\icon.svg', 'w').write(svg)
print('icon.svg guncellendi')
