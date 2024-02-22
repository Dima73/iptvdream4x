#!/bin/bash

case "$RESOLUTION" in
    1920x*)
        echo "config.skin.primary_skin=PLi-FullHD/skin.xml" >> /etc/enigma2/settings
        ;;
    *)
        if test -d /usr/share/enigma2/MetrixHD
        then
            echo "config.skin.primary_skin=MetrixHD/skin.xml" >> /etc/enigma2/settings
        else
            echo "config.skin.primary_skin=PLi-HD/skin.xml" >> /etc/enigma2/settings
        fi
        ;;
esac

exec x11vnc -forever
