# -*- coding: utf-8 -*-
"""Roster (aka. personnel directory)
"""

from five import grok
from plone import api
from z3c.table.table import getWeight

from zope.component import (
    getGlobalSiteManager,
    getUtility
)

from plone.app.viewletmanager.manager import OrderedViewletManager

from zope.publisher.interfaces.browser import IBrowserRequest

from zope.schema.interfaces import (
    IVocabularyFactory,
    IList
)
from zope.schema.vocabulary import SimpleTerm, SimpleVocabulary

from z3c.form.datamanager import AttributeField
from z3c.table.interfaces import (
    IColumn
)
from z3c.table import (
    table,
    column
)

from Products.CMFCore.utils import getToolByName

from plone.i18n.normalizer.interfaces import IIDNormalizer
from plone.memoize import view

from collective.roster.interfaces import (
    IPersonnelListing,
    IPerson,
    IRoster
)
from collective.roster.behaviors.interfaces import (
    IContactInfo,
    IOfficeInfo,
    ISubjectInfo

)
from collective.roster.utils import getFirstParent


from zope.i18nmessageid import MessageFactory as ZopeMessageFactory
_ = ZopeMessageFactory("collective.roster")


class RosterViewlets(OrderedViewletManager, grok.ViewletManager):
    """ Roster viewlet manager, which manages all roster related viewlets """
    grok.context(IRoster)
    grok.name("collective.roster.rosterviewlets")


class LinkViewlet(grok.Viewlet):
    grok.viewletmanager(RosterViewlets)
    grok.context(IRoster)
    grok.name("collective.roster.rosterviewlets.linkviewlet")


class LocalGroupsVocabulary(grok.GlobalUtility):
    """ Returns a new context bound vocabulary, which returns the
    groups defined in the nearest parent roster """

    grok.provides(IVocabularyFactory)
    grok.name("collective.roster.localgroups")

    def __call__(self, context):
        groups = []
        normalizer = getUtility(IIDNormalizer)
        roster = getFirstParent(context, IRoster)
        for group in getattr(roster, "groups", ()):
            if "|" in group:
                value, title = group.split("|", 1)
            else:
                value = title = group
            groups.append(
                SimpleTerm(value,
                           token=normalizer.normalize(group),
                           title=title)
            )
        return SimpleVocabulary(groups)


class DisplayColumnsVocabulary(grok.GlobalUtility):
    """ Returns a new context independent vocabulary, which return all the
    table columns registered for the roster interface """

    grok.provides(IVocabularyFactory)
    grok.name("collective.roster.columns")

    def _isColumnAdapter(self, obj):
        return obj.required == (IRoster, IBrowserRequest, IPersonnelListing)\
            and obj.provided == IColumn

    def __call__(self, context):
        gsm = getGlobalSiteManager()
        adapters = gsm.registeredAdapters()
        columns = filter(self._isColumnAdapter, adapters)
        terms = map(lambda x: SimpleTerm(x.name, x.name, x.factory.header),
                    columns)
        return SimpleVocabulary(terms)


#class RosterDataManager(grok.MultiAdapter, AttributeField):
#    """ z3c.form datamanager, which reverts the behavior of display columns
#    field to store hidden columns instead """
#
#    grok.adapts(IRoster, IList)
#
#    def _isColumnAdapter(self, obj):
#        return obj.required == (IRoster, IBrowserRequest, IPersonnelListing)\
#            and obj.provided == IColumn
#
#    def _getAllColumns(self):
#        gsm = getGlobalSiteManager()
#        adapters = gsm.registeredAdapters()
#        columns = filter(self._isColumnAdapter, adapters)
#        return map(lambda x: x.name, columns)
#
#    def get(self):
#        value = super(RosterDataManager, self).get()
#        if self.field.__name__ == "columns_hidden" and value is not None:
#            columns = self._getAllColumns()  # XXX: could use vocab instead
#            selection = [] if value is None else value  # value can be None
#            value = filter(lambda x: x not in selection, columns)
#        return value
#
#    def set(self, value):
#        if self.field.__name__ == "columns_hidden":
#            columns = self._getAllColumns()  # XXX: could use vocab instead
#            selection = [] if value is None else value  # value can be None
#            value = filter(lambda x: x not in selection, columns)
#        return super(RosterDataManager, self).set(value)


class GroupView(grok.View):
    """ Personnel listing view, which is composed using its own viewlet manager
    to make it extensible and configurable """

    grok.context(IRoster)
    grok.require("zope2.View")
    grok.name("groupview")

    def __init__(self, context, request):
        super(GroupView, self).__init__(context, request)

        vocabulary_factory = getUtility(IVocabularyFactory,
                                        name="collective.roster.localgroups")
        vocabulary = vocabulary_factory(self.context)
        self.tables = map(
            lambda group: PersonnelGroupListing(self.context, self.request,
                                                group),
            map(lambda term: term.value, vocabulary)
        )

    def update(self):
        super(GroupView, self).update()
        for table in self.tables:
            table.update()


class AlphaView(grok.View):
    """ A to Z view for all persons """
    grok.context(IRoster)
    grok.require("zope2.View")
    grok.name("alphaview")

    def __init__(self, context, request):
        super(AlphaView, self).__init__(context, request)
        self.table = PersonnelAlphaListing(self.context, self.request)

    def update(self):
        super(AlphaView, self).update()
        self.table.update()

    def atoz(self):
        """ Render A to Z links for template """
        # get current url for alphalinks
        url = api.portal.getRequest().getURL()
        self.table.render()
        output = ""
        for alpha in self.table.alpha:
            output += """<a class="alpha-anchor"
                       href="%s#%s">%s</a>""" % (url, alpha, alpha)
        return output


class GalleryView(GroupView):
    """ Gallery view for persons """
    grok.context(IRoster)
    grok.require("zope2.View")
    grok.name("galleryview")

    def update(self):
        pass


class PersonnelListing(table.Table):
    """ Personnel listing table, which can be exteneded with custom columns """
    grok.implements(IPersonnelListing)

    title = u""

    # CSS
    cssClasses = {'table': u"listing roster", 'td': u"notDraggable"}
    cssClassEven = u"even"
    cssClassOdd = u"odd"

    # Sort
    sortOn = 1  # (z3c.table expects sortOn to be either None, 0 or column
                   # order aware id[table-column-idx])

    # Batching
    batchProviderName = "plonebatch"
    batchSize = 10
    startBatchingAt = 99999

    def renderRow(self, row, cssClass=None):
        if api.content.get_state(row[0][0]) != 'published':
            cssClass = u'state-private'
        return super(PersonnelListing, self).renderRow(row, cssClass)

    def getBatchSize(self):
        return max(int(self.request.get(self.prefix + '-batchSize',
                                        self.batchSize)), 1)

    def setUpColumns(self):
        cols = super(PersonnelListing, self).setUpColumns()

        columns_display = getattr(self.context, "columns_display", [])

        if columns_display:
            cols_factory = getUtility(IVocabularyFactory,
                                      name="collective.roster.columns")
            cols_vocabulary = cols_factory(self.context)
            cols_all = [col.value for col in cols_vocabulary]

            cols_selected = [col for col in cols
                             if col.__name__ in columns_display
                             or col.__name__ not in cols_all]
            return cols_selected

        columns_hidden = getattr(self.context, "columns_hidden", [])

        if columns_hidden:
            return filter(lambda x: x.__name__ not in columns_hidden, cols)

        return cols

    def orderColumns(self):
        columns_display = getattr(self.context, "columns_display", [])
        if not columns_display:
            super(PersonnelListing, self).orderColumns()
        else:
            def sortKey(col):
                if col.__name__ in columns_display:
                    return columns_display.index(col.__name__)
                else:
                    return getWeight(col)
            self.columnCounter = 0
            self.columns = sorted(
                self.columns, key=sortKey)
            for col in self.columns:
                self.columnByName[col.__name__] = col
                idx = self.columnCounter
                col.id = '%s-%s-%s' % (self.prefix, col.__name__, idx)
                self.columnIndexById[col.id] = idx
                self.columnCounter += 1

    @property
    @view.memoize
    def values(self):
        pc = getToolByName(self.context, "portal_catalog")
        brains = pc(
            path="/".join(self.context.getPhysicalPath()),
            object_provides=IPerson.__identifier__
        )
        values = map(lambda x: x.getObject(), brains)
        return values


class PersonnelAlphaListing(PersonnelListing):

    alpha = []
    sortOn = None

    @property
    def values(self):
        values = super(PersonnelAlphaListing, self).values
        sort_by_title = lambda x: x.title.lower()
        sorted_values = sorted(values, key=sort_by_title)
        return sorted_values

    def update(self):
        super(PersonnelAlphaListing, self).update()
        self.alpha = []


class PersonnelGroupListing(PersonnelListing):

    sortOn = None

    def __init__(self, context, request, group):
        super(PersonnelGroupListing, self).__init__(context, request)
        self.group = group

    @property
    def title(self):
        vocabulary_factory = getUtility(IVocabularyFactory,
                                        name="collective.roster.localgroups")
        vocabulary = vocabulary_factory(self.context)
        term = vocabulary.getTerm(self.group)
        return term.title

    def renderRow(self, row, cssClass=None):
        if api.content.get_state(row[0][0].get('object')) != 'published':
            cssClass = u'state-private'
        return super(PersonnelListing, self).renderRow(row, cssClass)

    @property
    def anchorTitle(self):
        normalizer = getUtility(IIDNormalizer)
        return normalizer.normalize(self.title)

    """ Personnel values property, which provides catalog brains for all the
    persons with the same group as the currently rendered personnel listing
    table under the current personnel roster """
    @property
    def values(self):
        vocabulary_factory = getUtility(IVocabularyFactory,
                                        name="collective.roster.localgroups")
        vocabulary = vocabulary_factory(self.context)
        term = vocabulary.getTerm(self.group)

        pc = getToolByName(self.context, "portal_catalog")
        brains = pc(
            path="/".join(self.context.getPhysicalPath()),
            object_provides=IPerson.__identifier__,
            Subject=(term.title.encode('utf-8', 'ignore'),)  # are indexed by titles
        )
        values = [{'brain': brain, 'object': brain.getObject()}
                  for brain in brains]
        # values = map(lambda x: x.getObject(), brains)
        sort_by_title = lambda x: x['object'].title.lower()
        sorted_values = sorted(values, key=sort_by_title)
        return sorted_values


class AlphaColumn(grok.MultiAdapter, column.Column):

    grok.provides(IColumn)
    grok.adapts(IRoster, IBrowserRequest, PersonnelAlphaListing)
    grok.name("collective.roster.personnellisting.alpha")

    weight = -1

    header = _(u"#")

    def renderCell(self, obj):
        if not obj.last_name:
            return u""
        alpha = obj.last_name[0].upper()

        if not self.table.alpha or alpha != self.table.alpha[-1]:
            self.table.alpha.append(alpha)
            return u"""<a name="%s">%s</a>""" % (alpha, alpha)
        else:
            return u""


class SubjectColumn(grok.MultiAdapter, column.LinkColumn):
    """ Column, which renders person's subject"""

    grok.provides(IColumn)
    grok.adapts(IRoster, IBrowserRequest, IPersonnelListing)
    grok.name("collective.roster.personnellisting.subject")

    weight = 105

    header = _(u"Subject")

    def renderCell(self, obj):
        if isinstance(obj, dict):
            adapter = ISubjectInfo(obj.get('object'), None)
        else:
            adapter = ISubjectInfo(obj, None)
        if adapter:
            return getattr(adapter, "studysubject", None) or u""
        return u""


class TitleColumn(grok.MultiAdapter, column.LinkColumn):
    """ Column, which renders person's full name without title """

    grok.provides(IColumn)
    grok.adapts(IRoster, IBrowserRequest, IPersonnelListing)
    grok.name("collective.roster.personnellisting.title")

    weight = 99

    header = _(u"Name")

    def getLinkURL(self, obj):
        if isinstance(obj, dict):
            return obj.get('object').absolute_url()
        return obj.absolute_url()

    def getLinkContent(self, obj):
        if isinstance(obj, dict):
            obj = obj.get('object')
        title = u"%s %s" % (obj.last_name, obj.first_name)
        if type(title) != unicode:
            title = unicode(title, u"utf-8")
        return title


class SalutationColumn(grok.MultiAdapter, column.Column):
    """ Column which renders person's title"""

    grok.provides(IColumn)
    grok.adapts(IRoster, IBrowserRequest, IPersonnelListing)
    grok.name("collective.roster.personnellisting.salutation")

    weight = 100

    header = _(u"Title")

    def renderCell(self, obj):
        if isinstance(obj, dict):
            return obj.get('object').salutation
        return obj.salutation


class RoomColumn(grok.MultiAdapter, column.Column):
    """ Column, which renders person's room """

    grok.provides(IColumn)
    grok.adapts(IRoster, IBrowserRequest, IPersonnelListing)
    grok.name("collective.roster.personnellisting.room")

    weight = 101

    header = _(u"Room")

    def renderCell(self, obj):
        if isinstance(obj, dict):
            adapter = IOfficeInfo(obj.get('object'), None)
        else:
            adapter = IOfficeInfo(obj, None)
        if adapter:
            return getattr(adapter, "room", None) or u""
        return u""


class PhoneNumberColumn(grok.MultiAdapter, column.LinkColumn):
    """ Column, which renders person's phone number """

    grok.provides(IColumn)
    grok.adapts(IRoster, IBrowserRequest, IPersonnelListing)
    grok.name("collective.roster.personnellisting.phone_number")

    weight = 102

    header = _(u"Phone number")

    def getLinkURL(self, obj):
        if isinstance(obj, dict):
            adapter = IContactInfo(obj.get('object'), None)
        else:
            adapter = IContactInfo(obj, None)
        phone = getattr(adapter, "phone_number", None)
        if phone:
            return "tel:" + phone
        return u""

    def getLinkContent(self, obj):
        if isinstance(obj, dict):
            adapter = IContactInfo(obj.get('object'), None)
        else:
            adapter = IContactInfo(obj, None)
        if adapter:
            return getattr(adapter, "phone_number", u"") or u""
        return u""


class ShortNumberColumn(grok.MultiAdapter, column.LinkColumn):
    """ Column, which renders person's short number """

    grok.provides(IColumn)
    grok.adapts(IRoster, IBrowserRequest, IPersonnelListing)
    grok.name("collective.roster.personnellisting.short_number")

    weight = 103

    header = _(u"Short number")

    def getLinkURL(self, obj):
        if isinstance(obj, dict):
            adapter = IOfficeInfo(obj.get('object'), None)
        else:
            adapter = IOfficeInfo(obj, None)
        short_number = getattr(adapter, "short_number", None)
        if short_number:
            return "tel: %s" % (short_number,)
        return ""

    def getLinkContent(self, obj):
        if isinstance(obj, dict):
            adapter = IOfficeInfo(obj.get('object'), None)
        else:
            adapter = IOfficeInfo(obj, None)
        if adapter:
            return getattr(adapter, "short_number", None) or u""
        return u""


class EmailColumn(grok.MultiAdapter, column.LinkColumn):
    """ Column, which renders person's email address """

    grok.provides(IColumn)
    grok.adapts(IRoster, IBrowserRequest, IPersonnelListing)
    grok.name("collective.roster.personnellisting.email")

    weight = 104

    header = _(u"Email")

    def getLinkURL(self, obj):
        if isinstance(obj, dict):
            adapter = IContactInfo(obj.get('object'), None)
        else:
            adapter = IContactInfo(obj, None)
        email = getattr(adapter, "email", None)
        if email:
            return "mailto:" + email
        return ""

    def getLinkContent(self, obj):
        if isinstance(obj, dict):
            adapter = IContactInfo(obj.get('object'), None)
        else:
            adapter = IContactInfo(obj, None)
        if adapter:
            return getattr(adapter, "email", u"") or u""
        return u""
