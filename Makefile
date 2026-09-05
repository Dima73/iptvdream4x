PYTHON := python2.7
ARCH := all
DESTDIR ?= build
PACKAGEDIR ?= packages
DEB ?= n
UPDATE_PO ?= n
PROVIDER ?= all

plugin_name := IPtvDream
plugin_path := /usr/lib/enigma2/python/Plugins/Extensions/$(plugin_name)
skin_prefix := /usr/share/enigma2
  
ifeq ($(DEB),y)
pkgext := deb
else
pkgext := ipk
endif
architecture := $(ARCH)

build := $(DESTDIR)
plugindir = $(build)$(plugin_path)

all: package

pyfiles := src/__init__.py src/common.py src/compat.py src/dist.py src/plugin.py src/updater.py \
	src/cache.py \
	src/layer.py src/loc.py src/utils.py src/manager.py src/main.py src/settings.py \
	src/standby.py src/virtualkb.py src/server.py src/provision.py \
	src/lib/__init__.py src/lib/epg.py src/lib/tv.py \
	src/api/__init__.py src/api/abstract_api.py
datafiles := src/keymap_enigma.xml src/keymap_neutrino.xml src/IPtvDream.png

ifeq ($(PROVIDER),all)
pyfiles += src/api/api1.py src/api/teleprom.py src/api/raduga.py src/api/amigo.py src/api/emigranttv.py \
	src/api/pure.py \
	src/api/m3u.py src/api/edem_soveni.py src/api/edem.py src/api/shura.py \
	src/api/iptv_e2_soveni.py src/api/onecent_soveni.py \
	src/api/top_iptv.py src/api/koronaiptv.py src/api/shurik.py src/api/shara-tv.py \
	src/api/playlist.py src/api/1ott.py src/api/fox.py src/api/itv_live.py \
	src/api/ottg.py src/api/antifriz.py \
	src/api/kartina.py src/api/ktv.py src/api/newrus.py \
	src/api/cbilling.py src/api/ipstream.py src/api/tvteam.py \
	src/api/mywy.py src/api/naschetv.py src/api/ozo.py src/api/sovok.py src/api/baltic.py
datafiles += $(wildcard src/logo/*.png)
endif

ifeq ($(PROVIDER),73mtv)
pyfiles += src/api/m3u.py src/api/73mtv.py
datafiles += src/logo/73mtv.png
endif

pyext := pyo
pyinstall := $(pyfiles:src/%=$(plugindir)/%)
pycinstall := $(pyinstall:.py=.$(pyext))

$(pyinstall): $(plugindir)/%.py: src/%.py
	install -D -m644 $< $@

$(pycinstall): $(plugindir)/%.$(pyext): src/%.py
	install -d $(dir $@)
	$(PYTHON) -c 'import py_compile; py_compile.compile("$<", "$@")'


datainstall := $(patsubst src/%,$(plugindir)/%,$(datafiles))

$(datainstall): $(plugindir)/%: src/%
	install -D -m644 $< $@

$(plugindir)/LICENSE: LICENSE
	install -D -m644 $< $@

$(plugindir)/README.md: README.md
	install -D -m644 $< $@

install: $(plugindir)/LICENSE $(plugindir)/README.md


skin_dir := $(build)$(skin_prefix)/IPtvDream
skin_files := $(shell find skins/IPtvDream/ -name '*.png') skins/IPtvDream/iptvdream.xml
skin_install := $(patsubst skins/IPtvDream/%,$(skin_dir)/%,$(skin_files))

$(skin_install): $(skin_dir)/%: skins/IPtvDream/%
	install -D -m644 $< $@

skin-fhd_dir := $(build)$(skin_prefix)/IPtvDreamFHD
skin-fhd_files := $(shell find skins/IPtvDreamFHD/ -name '*.png') skins/IPtvDreamFHD/iptvdream.xml
skin-fhd_install := $(patsubst skins/IPtvDreamFHD/%,$(skin-fhd_dir)/%,$(skin-fhd_files))

$(skin-fhd_install): $(skin-fhd_dir)/%: skins/IPtvDreamFHD/%
	install -D -m644 $< $@

skin-contrast_dir := $(build)$(skin_prefix)/IPtvDreamContrast
skin-contrast_files := $(shell find skins/IPtvDreamContrast/ -name '*.png') skins/IPtvDreamContrast/iptvdream.xml
skin-contrast_install := $(patsubst skins/IPtvDreamContrast/%,$(skin-contrast_dir)/%,$(skin-contrast_files))

$(skin-contrast_install): $(skin-contrast_dir)/%: skins/IPtvDreamContrast/%
	install -D -m644 $< $@


skin-fhd-contrast_dir := $(build)$(skin_prefix)/IPtvDreamFHDContrast
skin-fhd-contrast_files := $(shell find skins/IPtvDreamFHDContrast/ -name '*.png') skins/IPtvDreamFHDContrast/iptvdream.xml
skin-fhd-contrast_install := $(patsubst skins/IPtvDreamFHDContrast/%,$(skin-fhd-contrast_dir)/%,$(skin-fhd-contrast_files))

$(skin-fhd-contrast_install): $(skin-fhd-contrast_dir)/%: skins/IPtvDreamFHDContrast/%
	install -D -m644 $< $@



skinxmls = $(addprefix skins/,$(addsuffix /iptvdream.xml,IPtvDream IPtvDreamFHD IPtvDreamContrast IPtvDreamFHDContrast))

$(skinxmls): %/iptvdream.xml: %/skin.xml
	python skin-post.py $< $@

prepare: $(skinxmls)


langs := uk ru en de lt

langs_po := $(addprefix po/,$(langs))
langs_po := $(addsuffix .po,$(langs_po))

moinstall := $(addprefix $(plugindir)/locale/,$(langs))
moinstall := $(addsuffix /LC_MESSAGES/IPtvDream.mo,$(moinstall))

$(moinstall): $(plugindir)/locale/%/LC_MESSAGES/$(plugin_name).mo: po/%.po
	install -d $(dir $@)
	msgfmt -o $@ $<

po/$(plugin_name).pot: $(pyfiles)
	xgettext -L python --from-code=UTF-8 -d $(plugin_name) -s -o $@ $^

ifeq ($(UPDATE_PO),y)

%.po: po/$(plugin_name).pot
	(! test -f $@) \
	&& msginit -l $@ -o $@ -i $< --no-translator \
	|| msgmerge --backup=none --no-location -s -N -U $@ $< \
	&& touch $@

endif

update-po:
	$(MAKE) UPDATE_PO=y $(langs_po)


bin_install := $(build)/usr/bin/hlsgw.py $(build)/usr/bin/hlsgwd.sh

$(bin_install): $(build)/usr/bin/%: tools/%
	install -D -m755 $< $@

ifeq ($(BYTECODE),n)
pycinstall :=
endif

install: $(pyinstall) $(pycinstall) $(datainstall) $(skin_install) $(skin-fhd_install) $(skin-contrast_install) $(skin-fhd-contrast_install) $(moinstall) $(bin_install)
	install -d $(build)/etc/iptvdream


version: src/dist.py
	mkdir -p $(dir $@)
	test  `cat $< |sed -n 's/^\s*NAME\s*=\s*"\(.*\)"$$/\1/p'` = '$(PROVIDER)'
	cat $< |sed -n 's/^\s*VERSION\s*=\s*"\(.*\)"$$/version=\1/p' > $@

include version

name := enigma2-plugin-extensions-$(shell echo $(plugin_name)-$(PROVIDER) | tr A-Z a-z)
provider := $(shell echo $(PROVIDER) |tr A-Z a-z)
pkgname := $(name)_$(version)_$(architecture)

controldir := DEBIAN

$(build)/DEBIAN/control: $(controldir)/control version
	install -d $(dir $@)
	cp $< $@
	sed -i $@ -e "s/^Package:.*/Package: $(name)/"
	sed -i $@ -e "s/^Version:.*/Version: $(version)/"
	sed -i $@ -e "s/^Architecture:.*/Architecture: $(architecture)/"

hooks := $(filter-out $(controldir)/control, $(wildcard $(controldir)/*))
hooks := $(patsubst $(controldir)/%, $(build)/DEBIAN/%, $(hooks))

$(hooks): $(build)/DEBIAN/%: $(controldir)/%
	install -m 755 $< $@


pkgdir := $(PACKAGEDIR)

$(pkgdir)/$(pkgname).$(pkgext): install $(build)/DEBIAN/control $(hooks)
	@ ! test -f "$@" || (echo "Error: package $(pkgname).$(pkgext) already exists"; false)
	mkdir -p $(pkgdir)
	dpkg-deb -b -Zgzip $(build) tmp.deb
	mv tmp.deb $@
	echo '$(version)' > $(pkgdir)/version-$(provider).txt
	ln -sf $(pkgname).$(pkgext) $(pkgdir)/latest_$(provider).$(pkgext)

package: $(pkgdir)/$(pkgname).$(pkgext) info

info:
	echo '{"name": "$(name)", "version": "$(version)"}' > $@.json

clean:
	rm -rf build
	rm -f version

.PHONY: prepare install package info update-po clean
