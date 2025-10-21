#!/bin/sh
#
# Simple script to daemonize hlsgw.py
#

NAME=hlsgw.py
DAEMON=/usr/bin/$NAME

#test -x "$DAEMON" || exit 1

PYVERSION=$(python -V 2>&1 | awk '{print $2}')
case $PYVERSION in
	2.*)
		PYEXT=pyo
		PYNAME=python
		echo "Python version $PYVERSION"
		;;
	3.*)
		PYEXT=pyc
		PYNAME=python3
		echo "Python version $PYVERSION"
		;;
esac
if [ -z $PYVERSION ]; then
	echo "Unable to determine installed Python version!"
	exit 1
fi

case "$1" in
  # busybox realization of start-stop-daemon requires -x argument
  # otherwise it does not detect already running process
  start)
    #start-stop-daemon -S -q -n "$NAME" -x /usr/bin/$PYNAME -a "$DAEMON" -b
    /usr/bin/$PYNAME $DAEMON &
    retval=$?
    if test $retval -eq 0; then
        echo "started $NAME"
    fi
    exit $retval
    ;;
  stop)
    #start-stop-daemon -K -n "$NAME" -x /usr/bin/$PYNAME
    EPID=`pidof /usr/bin/$PYNAME | head -n1`
    kill -9 $EPID 2>/dev/null
    ;;
  restart)
    $0 stop && $0 start
    ;;
  *)
    echo "Usage: $0 {start|stop|restart}" >&2
    exit 1
    ;;
esac

exit 0
