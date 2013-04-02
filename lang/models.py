# -*- coding: utf-8 -*-
#
# Copyright © 2012 - 2013 Michal Čihař <michal@cihar.com>
#
# This file is part of Weblate <http://weblate.org/>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#

from django.db import models
from django.utils.translation import ugettext as _, pgettext_lazy
from django.db.models import Sum
from translate.lang.data import languages
from lang import data

from south.signals import post_migrate
from django.db.models.signals import post_syncdb
from django.dispatch import receiver
import weblate

# Plural types definition
PLURAL_NONE = 0
PLURAL_ONE_OTHER = 1
PLURAL_ONE_FEW_OTHER = 2
PLURAL_ARABIC = 3
PLURAL_ONE_TWO_OTHER = 4
PLURAL_ONE_TWO_THREE_OTHER = 5
PLURAL_ONE_TWO_FEW_OTHER = 6
PLURAL_ONE_OTHER_ZERO = 7
PLURAL_ONE_FEW_MANY_OTHER = 8
PLURAL_TWO_OTHER = 9
PLURAL_ONE_TWO_FEW_MANY_OTHER = 10
PLURAL_UNKNOWN = 666

# Plural equation - type mappings
PLURAL_MAPPINGS = (
    (data.ONE_OTHER_PLURALS, PLURAL_ONE_OTHER),
    (data.ONE_FEW_OTHER_PLURALS, PLURAL_ONE_FEW_OTHER),
    (data.ONE_TWO_OTHER_PLURALS, PLURAL_ONE_TWO_OTHER),
    (data.ONE_TWO_FEW_OTHER_PLURALS, PLURAL_ONE_TWO_FEW_OTHER),
    (data.ONE_TWO_THREE_OTHER_PLURALS, PLURAL_ONE_TWO_THREE_OTHER),
    (data.ONE_OTHER_ZERO_PLURALS, PLURAL_ONE_OTHER_ZERO),
    (data.ONE_FEW_MANY_OTHER_PLURALS, PLURAL_ONE_FEW_MANY_OTHER),
    (data.TWO_OTHER_PLURALS, PLURAL_TWO_OTHER),
    (data.ONE_TWO_FEW_MANY_OTHER_PLURALS, PLURAL_ONE_TWO_FEW_MANY_OTHER),
)


def get_plural_type(code, pluralequation):
    '''
    Gets correct plural type for language.
    '''
    # Remove not needed parenthesis
    if pluralequation[-1] == ';':
        pluralequation = pluralequation[:-1]
    if pluralequation[0] == '(' and pluralequation[-1] == ')':
        pluralequation = pluralequation[1:-1]

    # Get base language code
    base_code = code.replace('_', '-').split('-')[0]

    # No plural
    if pluralequation == '0':
        return PLURAL_NONE

    # Standard plural equations
    for mapping in PLURAL_MAPPINGS:
        if pluralequation in mapping[0]:
            return mapping[1]

    # Arabic special case
    if base_code in ('ar'):
        return PLURAL_ARABIC

    # Log error in case of uknown mapping
    weblate.logger.error(
        'Can not guess type of plural for %s: %s', code, pluralequation
    )

    return PLURAL_UNKNOWN


class LanguageManager(models.Manager):
    def auto_get_or_create(self, code):
        '''
        Gets matching language for code (the code does not have to be exactly
        same, cs_CZ is same as cs-CZ) or creates new one.
        '''

        # First try getting langauge as is
        try:
            return self.get(code=code)
        except Language.DoesNotExist:
            pass

        # Parse the string
        if '-' in code:
            lang, country = code.split('-', 1)
        elif '_' in code:
            lang, country = code.split('_', 1)
        else:
            lang = code
            country = None

        # Try "corrected" code
        if country is not None:
            newcode = '%s_%s' % (lang.lower(), country.upper())
        else:
            newcode = lang.lower()
        try:
            return self.get(code=newcode)
        except Language.DoesNotExist:
            pass

        # Try canonical variant
        if newcode in data.DEFAULT_LANGS:
            try:
                return self.get(code=lang.lower())
            except Language.DoesNotExist:
                pass

        # Create new one
        return self.auto_create(code)

    def auto_create(self, code):
        '''
        Automatically creates new language based on code and best guess
        of parameters.
        '''
        # Create standard language
        lang = Language.objects.create(
            code=code,
            name='%s (generated)' % code,
            nplurals=2,
            pluralequation='(n != 1)',
        )
        # Try cs_CZ instead of cs-CZ
        if '-' in code:
            try:
                baselang = Language.objects.get(code=code.replace('-', '_'))
                lang.name = baselang.name
                lang.nplurals = baselang.nplurals
                lang.pluralequation = baselang.pluralequation
                lang.save()
                return lang
            except Language.DoesNotExist:
                pass

        # In case this is just a different variant of known language, get
        # params from that
        if '_' in code or '-' in code:
            parts = code.split('_')
            if len(parts) == 1:
                parts = code.split('-')
            try:
                baselang = Language.objects.get(code=parts[0])
                lang.name = baselang.name
                lang.nplurals = baselang.nplurals
                lang.pluralequation = baselang.pluralequation
                lang.direction = baselang.direction
                lang.save()
                return lang
            except Language.DoesNotExist:
                pass
        return lang

    def setup(self, update):
        '''
        Creates basic set of languages based on languages defined in ttkit
        and on our list of extra languages.
        '''

        # Languages from ttkit
        for code, props in languages.items():
            lang, created = Language.objects.get_or_create(
                code=code
            )

            # Should we update existing?
            if not update and not created:
                continue

            # Set language name
            lang.name = props[0].split(';')[0]
            lang.fixup_name()

            # Set number of plurals and equation
            lang.nplurals = props[1]
            lang.pluralequation = props[2].strip(';')
            lang.fixup_plurals()

            # Set language direction
            lang.set_direction()

            # Get plural type
            lang.plural_tupe = get_plural_type(
                lang.code,
                lang.pluralequation
            )

            # Save language
            lang.save()

        # Create Weblate extra languages
        for props in data.EXTRALANGS:
            lang, created = Language.objects.get_or_create(
                code=props[0]
            )

            # Should we update existing?
            if not update and not created:
                continue

            lang.name = props[1]
            lang.nplurals = props[2]
            lang.pluralequation = props[3]

            if props[0] in data.RTL_LANGS:
                lang.direction = 'rtl'
            else:
                lang.direction = 'ltr'
            lang.save()

    def have_translation(self):
        '''
        Returns list of languages which have at least one translation.
        '''
        return self.filter(translation__total__gt=0).distinct()


@receiver(post_syncdb)
@receiver(post_migrate)
def setup_lang(sender, app, **kwargs):
    '''
    Hook for creating basic set of languages on database migration.
    '''
    if app == 'lang' or getattr(app, '__name__', '') == 'lang.models':
        Language.objects.setup(False)


# Plural names mapping
PLURAL_NAMES = {
    PLURAL_NONE: ('',),
    PLURAL_ONE_OTHER: (
        pgettext_lazy('Plural form description', 'One'),
        pgettext_lazy('Plural form description', 'Other'),
    ),
    PLURAL_ONE_FEW_OTHER: (
        pgettext_lazy('Plural form description', 'One'),
        pgettext_lazy('Plural form description', 'Few'),
        pgettext_lazy('Plural form description', 'Other'),
    ),
    PLURAL_ARABIC: (
        pgettext_lazy('Plural form description', 'Zero'),
        pgettext_lazy('Plural form description', 'One'),
        pgettext_lazy('Plural form description', 'Two'),
        pgettext_lazy('Plural form description', 'Few'),
        pgettext_lazy('Plural form description', 'Many'),
        pgettext_lazy('Plural form description', 'Other'),
    ),
    PLURAL_ONE_TWO_OTHER: (
        pgettext_lazy('Plural form description', 'One'),
        pgettext_lazy('Plural form description', 'Two'),
        pgettext_lazy('Plural form description', 'Other'),
    ),
    PLURAL_ONE_TWO_THREE_OTHER: (
        pgettext_lazy('Plural form description', 'One'),
        pgettext_lazy('Plural form description', 'Two'),
        pgettext_lazy('Plural form description', 'Three'),
        pgettext_lazy('Plural form description', 'Other'),
    ),
    PLURAL_ONE_TWO_FEW_OTHER: (
        pgettext_lazy('Plural form description', 'One'),
        pgettext_lazy('Plural form description', 'Two'),
        pgettext_lazy('Plural form description', 'Few'),
        pgettext_lazy('Plural form description', 'Other'),
    ),
    PLURAL_ONE_OTHER_ZERO: (
        pgettext_lazy('Plural form description', 'One'),
        pgettext_lazy('Plural form description', 'Other'),
        pgettext_lazy('Plural form description', 'Zero'),
    ),
    PLURAL_ONE_FEW_MANY_OTHER: (
        pgettext_lazy('Plural form description', 'One'),
        pgettext_lazy('Plural form description', 'Few'),
        pgettext_lazy('Plural form description', 'Many'),
        pgettext_lazy('Plural form description', 'Other'),
    ),
    PLURAL_ONE_TWO_FEW_MANY_OTHER: (
        pgettext_lazy('Plural form description', 'One'),
        pgettext_lazy('Plural form description', 'Two'),
        pgettext_lazy('Plural form description', 'Few'),
        pgettext_lazy('Plural form description', 'Many'),
        pgettext_lazy('Plural form description', 'Other'),
    ),
    PLURAL_TWO_OTHER: (
        pgettext_lazy('Plural form description', 'Two'),
        pgettext_lazy('Plural form description', 'Other'),
    ),
}


class Language(models.Model):
    PLURAL_CHOICES = (
        (PLURAL_NONE, 'None'),
        (PLURAL_ONE_OTHER, 'One/other (classic plural)'),
        (PLURAL_ONE_FEW_OTHER, 'One/few/other (Slavic languages)'),
        (PLURAL_ARABIC, 'Arabic languages'),
        (PLURAL_ONE_TWO_OTHER, 'One/two/other'),
        (PLURAL_ONE_TWO_FEW_OTHER, 'One/two/few/other'),
        (PLURAL_ONE_TWO_THREE_OTHER, 'One/two/three/other'),
        (PLURAL_ONE_OTHER_ZERO, 'One/other/zero'),
        (PLURAL_ONE_FEW_MANY_OTHER, 'One/few/many/other'),
        (PLURAL_TWO_OTHER, 'Two/other'),
        (PLURAL_ONE_TWO_FEW_MANY_OTHER, 'One/two/few/many/other'),
        (PLURAL_UNKNOWN, 'Unknown'),
    )
    code = models.SlugField(unique=True)
    name = models.CharField(max_length=100)
    nplurals = models.SmallIntegerField(default=0)
    pluralequation = models.CharField(max_length=255, blank=True)
    direction = models.CharField(
        max_length=3,
        default='ltr',
        choices=(('ltr', 'ltr'), ('rtl', 'rtl')),
    )
    plural_type = models.IntegerField(
        choices=PLURAL_CHOICES,
        default=PLURAL_ONE_OTHER
    )

    objects = LanguageManager()

    class Meta:
        ordering = ['name']

    def __unicode__(self):
        if (not '(' in self.name
                and ('_' in self.code or '-' in self.code)
                and self.code not in ('zh_TW', 'zh_CN')):
            return '%s (%s)' % (_(self.name), self.code)
        return _(self.name)

    def get_plural_form(self):
        '''
        Returns plural form like gettext understands it.
        '''
        return 'nplurals=%d; plural=%s;' % (self.nplurals, self.pluralequation)

    def get_plural_label(self, idx):
        '''
        Returns label for plural form.
        '''
        try:
            return unicode(PLURAL_NAMES[self.plural_type][idx])
        except:
            if idx == 0:
                return _('Singular')
            elif idx == 0:
                return _('Plural')
            return _('Plural form %d') % idx

    @models.permalink
    def get_absolute_url(self):
        return ('show_language', (), {
            'lang': self.code
        })

    def get_translated_percent(self):
        '''
        Returns status of translations in this language.
        '''
        from trans.models import Translation

        translations = Translation.objects.filter(
            language=self
        ).aggregate(
            Sum('translated'),
            Sum('total')
        )

        translated = translations['translated__sum']
        total = translations['total__sum']

        # Prevent division by zero on no translations
        if total == 0:
            return 0
        return round(translated * 100.0 / total, 1)

    def get_html(self):
        '''
        Returns html attributes for markup in this language, includes
        language and direction.
        '''
        return 'lang="%s" dir="%s"' % (self.code, self.direction)

    def fixup_name(self):
        '''
        Fixes name, in most cases when wrong one is provided by ttkit.
        '''
        # Fixups (mostly shortening) of langauge names
        if self.code == 'ia':
            self.name = 'Interlingua'
        elif self.code == 'el':
            self.name = 'Greek'
        elif self.code == 'st':
            self.name = 'Sotho'
        elif self.code == 'oc':
            self.name = 'Occitan'
        elif self.code == 'nb':
            self.name = 'Norwegian Bokmål'
        elif self.code == 'pa':
            self.name = 'Punjabi'
        elif self.code == 'zh_CN':
            self.name = 'Simplified Chinese'
        elif self.code == 'zh_TW':
            self.name = 'Traditional Chinese'

    def set_direction(self):
        '''
        Sets default direction for language.
        '''
        if self.code in data.RTL_LANGS:
            self.direction = 'rtl'
        else:
            self.direction = 'ltr'

    def fixup_plurals(self):
        '''
        Fixes plurals to be in consistent form and to
        correct some mistakes in ttkit.
        '''

        # Split out plural equation when it is as whole
        if 'nplurals=' in self.pluralequation:
            parts = self.pluralequation.split(';')
            self.nplurals = int(parts[0][9:])
            self.pluralequation = parts[1][8:]

        # Strip not needed parenthesis
        if self.pluralequation[0] == '(' and self.pluralequation[-1] == ')':
            self.pluralequation = self.pluralequation[1:-1]

        # Fixes for broken plurals
        if self.code in ['kk', 'fa']:
            # Kazakh and Persian should have plurals, ttkit says it does
            # not have
            self.nplurals = 2
            self.pluralequation = 'n != 1'
