from django.db import models
from django.db.models.signals import pre_delete, pre_save
from django.contrib.auth.models import User, Group
from django.utils.translation import ugettext_lazy as _
from django.conf import settings
from py_etherpad import EtherpadLiteClient
from django.db.models.loading import get_model   

import urllib
import types

def get_group_model(): 
    model_name = getattr(settings, 'ETHERPAD_GROUP_MODEL', 'django.contrib.auth.Group')
    group_app, group_model = model_name.rsplit('.', 1)
    GroupModel = get_model(group_app, group_model)
    return GroupModel


import string
import random

class PadServer(models.Model):
    """Schema and methods for etherpad-lite servers
    """
    title = models.CharField(max_length=256)
    url = models.URLField(
        max_length=256,
        verify_exists=False,
        verbose_name=_('URL')
    )
    apikey = models.CharField(max_length=256, verbose_name=_('API key'))
    notes = models.TextField(_('description'), blank=True)

    class Meta:
        verbose_name = _('server')

    def __unicode__(self):
        return self.url

    @property
    def apiurl(self):
        if self.url[-1:] == '/':
            return "%sapi" % self.url
        else:
            return "%s/api" % self.url


class PadGroup(models.Model):
    """Schema and methods for etherpad-lite groups
    """
    group = models.ForeignKey(Group)
    groupID = models.CharField(max_length=256, blank=True)
    server = models.ForeignKey(PadServer)

    class Meta:
        verbose_name = _('group')

    def __unicode__(self):
        return self._group.__unicode__()

    @property
    def epclient(self):
        return EtherpadLiteClient(self.server.apikey, self.server.apiurl)

    @property
    def _group(self):
        GroupModel = get_group_model()
        reverse_field_name = getattr(settings, 'ETHERPAD_GROUP_FIELD_NAME', 'profile_group')
        
        if getattr(self, reverse_field_name, None) is not None:
            return getattr(self, reverse_field_name)
        
        field_name = getattr(settings, 'ETHERPAD_GROUP_PAD_FIELD_NAME', 'pad_group')

        if field_name not in [f.name for f in GroupModel._meta.fields]:
            raise Exception('Field %s not found on model %s' % (field_name, model_name))

        return GroupModel.objects.get(**{field_name: self})      

    def _get_random_id(self, size=6,
        chars=string.ascii_uppercase + string.digits + string.ascii_lowercase):
        """ To make the ID unique, we generate a randomstring
        """
        return ''.join(random.choice(chars) for x in range(size))    

    def map_to_etherpad(self):
        result = self.epclient.createGroupIfNotExistsFor(self._group.id.__str__())
        self.groupID = result['groupID']

    def Destroy(self):
        # First find and delete all associated pads
        Pad.objects.filter(group=self).delete()
        try:
            return self.epclient.deleteGroup(self.groupID)
        except ValueError, e:
            # Already gone? Good.
            pass

class PadAuthor(models.Model):
    """Schema and methods for etherpad-lite authors
    """
    user = models.ForeignKey(User)
    authorID = models.CharField(max_length=256, blank=True)
    server = models.ForeignKey(PadServer)
    group = models.ManyToManyField(
        PadGroup,
        blank=True,
        null=True,
        related_name='authors'
    )

    class Meta:
        verbose_name = _('author')

    def __unicode__(self):
        return self.user.__unicode__()

    @property
    def epclient(self):
        return EtherpadLiteClient(self.server.apikey, self.server.apiurl)

    def map_to_etherpad(self):
        default_author_name_mapper = lambda user: user.__unicode__()
        author_name_mapper = getattr(settings, 'ETHERPAD_AUTHOR_NAME_MAPPER', default_author_name_mapper)

        if not isinstance(author_name_mapper, types.FunctionType):
            author_name_mapper = default_author_name_mapper

        result = self.epclient.createAuthorIfNotExistsFor(
            self.user.id.__str__(),
            name=author_name_mapper(self.user)
        )
        self.authorID = result['authorID']
        return result

    def GroupSynch(self, *args, **kwargs):
        members_field_name = getattr(settings, 'ETHERPAD_GROUP_USERS_FIELD_NAME', 'user_set')
        pad_field_name = getattr(settings, 'ETHERPAD_GROUP_PAD_FIELD_NAME', 'pad_group')
        
        GroupModel = get_group_model()

        groups = GroupModel.objects.filter(**{"%s__in" % members_field_name: [self.user.id]})

        for ag in groups:
            try:
                gr = getattr(GroupModel.objects.get(**{pad_field_name: self}), pad_field_name)
            except GroupModel.DoesNotExist:
                gr = False
            if (isinstance(gr, PadGroup)):
                self.group.add(gr)

class Pad(models.Model):
    """Schema and methods for etherpad-lite pads
    """
    name = models.CharField(max_length=256)
    server = models.ForeignKey(PadServer)
    group = models.ForeignKey(PadGroup)

    def __unicode__(self):
        return self.name

    @property
    def link(self):
        return "%sp/%s" % (self.server.url, urllib.quote_plus(self.padid))

    @property
    def padid(self):
        return "%s$%s" % (self.group.groupID, self.name)

    @property
    def epclient(self):
        return EtherpadLiteClient(self.server.apikey, self.server.apiurl)

    def Create(self):
        return self.epclient.createGroupPad(self.group.groupID, self.name)

    def Destroy(self):
        return self.epclient.deletePad(self.padid)

    def isPublic(self):
        result = self.epclient.getPublicStatus(self.padid)
        return result['publicStatus']

    def ReadOnly(self):
        return self.epclient.getReadOnlyID(self.padid)

def padCreate(sender, instance, **kwargs):
    instance.Create()
pre_save.connect(padCreate, sender=Pad)

def padDel(sender, instance, **kwargs):
    instance.Destroy()
pre_delete.connect(padDel, sender=Pad)
pre_delete.connect(padDel, sender=PadGroup)

def padObjectPreSave(sender, instance, **kwargs):
    instance.map_to_etherpad()
pre_save.connect(padObjectPreSave, sender=PadGroup)
pre_save.connect(padObjectPreSave, sender=PadAuthor)

def groupDel(sender, instance, **kwargs):

    # We are trying to make this work generically for (almost) any
    # group-like model Therefore, this signal listens to every
    # pre_delete and filters on the actual model

    GroupModel = get_group_model()

    if GroupModel != sender:
        return 
 
    field_name = getattr(settings, 'ETHERPAD_GROUP_PAD_FIELD_NAME', 'pad_group')

    if field_name not in [f.name for f in GroupModel._meta.fields]:
        return 

    padGrp = getattr(GroupModel.objects.get(pk=instance.id), field_name, None)

    if padGrp is None:
        return
    
    padGrp.Destroy()

pre_delete.connect(groupDel)
