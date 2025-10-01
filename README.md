Skripti valokuvien ja videotiedostojen konvertointiin Immichin ymmärtämään formaattiin. (Immich kyllä ymmärtää vanhempia formaatteja, mutta päivämäärät mitä sattuu)
Valokuville lisätään metatietoihin puuttuva päivämäärä joko date created tai date modified perusteella, riippuen kumpi on vanhempi. Itse tiedostoja ei varsinaisesti muuteta, 
poikkeuksena .avi-videoit, joista skripti luo uudet .mp4-muotoiset videot nykystandardien mukaan. Optiolla --delete-originals poistetaan onnistuneesti muutetut .avi-tiedostot.
--dry-run argumentilla voi kokeilla skriptiä tekemättä muutoksia. Tämä ei välttämättä huomaa muutoksia tehdessä sattuvia mahdollisia virheitä.

AJAMINEN VAROVASTI JA OMALLA VASTUULLA!!!
Tämä muuttaa olemassa olevia tiedostoja! Aja vaan jos olet varma, ettei tiedostojen muuttuminen haittaa! Suosittelen pitämään varmuuskopioita.

Palvelimelta tiedostojen kopioiminen Windowsilla esim.
robocopy "\\<source_ip>\path" "C:\path" /E /COPY:DT /DCOPY:T

Vaatimukset:
- Python 3
- pip install piexif hachoir
- ffmpeg (https://ffmpeg.org/download.html)

Varmista, että tiedostosijainti on oikein script.py:ssä
ROOT_DIR = r"TÄHÄN_OMA_POLKU"

Ajo:
python script.py

kokeilu:
python script.py --dry-run

Avi-tiedostojen automaattinen poisto samalla:
python script.py --delete-originals
# PhotoConversionTool
