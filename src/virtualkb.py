# -*- coding: utf-8 -*-
# Enigma2 IPtvDream player framework
#
#  Copyright (c) 2015 Alex Maystrenko <alexeytech@gmail.com>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

from __future__ import print_function

from Screens.VirtualKeyBoard import VirtualKeyBoard as VirtualKeyBoard_e2

kbd_languages = {
	"en_EN": ([
		[u"EXIT", u"1", u"2", u"3", u"4", u"5", u"6", u"7", u"8", u"9", u"0", u"BACKSPACE"],
		[u"q", u"w", u"e", u"r", u"t", u"y", u"u", u"i", u"o", u"p", u"-", u"["],
		[u"a", u"s", u"d", u"f", u"g", u"h", u"j", u"k", u"l", u";", u"'", u"\\"],
		[u"<", u"z", u"x", u"c", u"v", u"b", u"n", u"m", u",", ".", u"/", u"CLEAR"],
		[u"SHIFT", u"SPACE", u"OK"]],
		[
		[u"EXIT", u"!", u"@", u"#", u"$", u"%", u"^", u"&", u"(", u")", u"=", u"BACKSPACE"],
		[u"Q", u"W", u"E", u"R", u"T", u"Y", u"U", u"I", u"O", u"P", u"*", u"]"],
		[u"A", u"S", u"D", u"F", u"G", u"H", u"J", u"K", u"L", u"?", u'"', u"|"],
		[u">", u"Z", u"X", u"C", u"V", u"B", u"N", u"M", u";", u":", u"_", u"CLEAR"],
		[u"SHIFT", u"SPACE", u"OK"]]),
	"el_GR": ([
		[u"EXIT", u"1", u"2", u"3", u"4", u"5", u"6", u"7", u"8", u"9", u"0", u"BACKSPACE"],
		[u";", u"ς", u"ε", u"ρ", u"τ", u"υ", u"θ", u"ι", u"ο", u"π", u"[", u"]"],
		[u"α", u"α", u"δ", u"φ", u"γ", u"η", u"ξ", u"κ", u"λ", u"΄", u"'", u"\\"],
		[u"<", u"ζ", u"χ", u"ψ", u"ω", u"β", u"ν", u"μ", u",", ".", u"/", u"CLEAR"],
		[u"SHIFT", u"SPACE", u"OK"]],
		[
		[u"EXIT", u"1", u"2", u"3", u"4", u"5", u"6", u"7", u"8", u"9", u"0", u"BACKSPACE"],
		[u";", u"ς", u"ε", u"ρ", u"τ", u"υ", u"θ", u"ι", u"ο", u"π", u"[", u"]"],
		[u"α", u"α", u"δ", u"φ", u"γ", u"η", u"ξ", u"κ", u"λ", u"΄", u"'", u"\\"],
		[u"<", u"ζ", u"χ", u"ψ", u"ω", u"β", u"ν", u"μ", u",", ".", u"/", u"CLEAR"],
		[u"SHIFT", u"SPACE", u"OK"]]),
	"ru_RU": ([
		[u"EXIT", u"1", u"2", u"3", u"4", u"5", u"6", u"7", u"8", u"9", u"0", u"BACKSPACE"],
		[u"й", u"ц", u"у", u"к", u"е", u"н", u"г", u"ш", u"щ", u"з", u"х", u"+"],
		[u"ф", u"ы", u"в", u"а", u"б", u"п", u"р", u"о", u"л", u"д", u"ж", u"#"],
		[u"<", u"э", u"я", u"ч", u"с", u"м", u"и", u"т", u",", ".", u"-", u"CLEAR"],
		[u"SHIFT", u"SPACE", u"@", u"ь", u"ю", u"ъ", u"OK"]],
		[
		[u"EXIT", u"!", u'"', u"§", u"$", u"%", u"&", u"/", u"(", u")", u"=", u"BACKSPACE"],
		[u"Й", u"Ц", u"У", u"К", u"Е", u"Н", u"Г", u"Ш", u"Щ", u"З", u"I", u"Х", u"*"],
		[u"Ф", u"Ы", u"В", u"А", u"П", u"Р", u"О", u"О", u"Л", u"Д", u"Ж", u"'"],
		[u">", u"Э", u"Я", u"Ч", u"С", u"М", u"И", u"Т", u";", u":", u"_", u"CLEAR"],
		[u"SHIFT", u"SPACE", u"?", u"\\", u"Ь", u"Б", u"Ю", u"Ъ", u"OK"]])
}


class VirtualKeyBoard(VirtualKeyBoard_e2):
	def __init__(self, session, title="", text="", languages=None):
		if languages is None:
			languages = list(kbd_languages.keys())
		self.languages = {}
		for lang in languages:
			try:
				self.languages[lang] = kbd_languages[lang]
			except KeyError:
				continue
		VirtualKeyBoard_e2.__init__(self, session, title=title, text=text)

	def setLang(self):
		print("setLang", self.lang)
		l = list(self.languages.keys())
		if self.lang in l:
			i = l.index(self.lang)
		else:
			self.lang = l[0]
			i = 0
		self.nextLang = l[(i + 1) % len(l)]

		self.keys_list = self.languages[self.lang][0]
		self.shiftkeys_list = self.languages[self.lang][1]

		self["country"].setText(self.lang)
		self.max_key = 47+len(self.keys_list[4])
