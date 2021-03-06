# encoding: utf-8
import datetime

from django.conf import settings
from django.core.urlresolvers import reverse
from django.db import models

from django.contrib.auth.models import User
from django.contrib.contenttypes.models import ContentType

from markitup.fields import MarkupField

from timezones.utils import localtime_for_timezone

from symposion.conference.models import PresentationKind, PresentationCategory


class Track(models.Model):
    
    name = models.CharField(max_length=65)
    room = models.CharField(max_length=100, blank=True)
    
    def __unicode__(self):
        return self.name


class Session(models.Model):
    
    track = models.ForeignKey(Track, null=True, related_name="sessions")
    
    def sorted_slots(self):
        ct = ContentType.objects.get_for_model(Presentation)
        return self.slots.filter(kind=ct).order_by("start")
    
    # @@@ cache?
    def start(self):
        slots = self.sorted_slots()
        if slots:
            return localtime_for_timezone(list(slots)[0].start, settings.SCHEDULE_TIMEZONE)
        else:
            return None
    
    # @@@ cache?
    def end(self):
        slots = self.sorted_slots()
        if slots:
            return localtime_for_timezone(list(slots)[-1].end, settings.SCHEDULE_TIMEZONE)
        else:
            return None
    
    def __unicode__(self):
        start = self.start() 
        end = self.end()
        if start and end:
            return u"%s: %s — %s" % (
                start.strftime("%a"),
                start.strftime("%X"),
                end.strftime("%X")
            )
        return u""


class SessionRole(models.Model):
    
    SESSION_ROLE_CHAIR = 1
    SESSION_ROLE_RUNNER = 2
    
    SESSION_ROLE_TYPES = [
        (SESSION_ROLE_CHAIR, "Session Chair"),
        (SESSION_ROLE_RUNNER, "Session Runner"),
    ]
    
    session = models.ForeignKey(Session)
    user = models.ForeignKey(User)
    role = models.IntegerField(choices=SESSION_ROLE_TYPES)
    status = models.NullBooleanField()
    
    submitted = models.DateTimeField(default = datetime.datetime.now)
    
    class Meta:
        unique_together = [("session", "user", "role")]


# @@@ precreate the Slots with proposal == None and then making the schedule is just updating slot.proposal and/or title/notes
class Slot(models.Model):
    
    title = models.CharField(max_length=100, null=True, blank=True)
    start = models.DateTimeField()
    end = models.DateTimeField()
    kind = models.ForeignKey(ContentType, null=True, blank=True)
    track = models.ForeignKey(Track, null=True, blank=True, related_name="slots")
    session = models.ForeignKey(Session, null=True, blank=True, related_name="slots")
    
    def content(self):
        if self.kind_id:
            return self.kind.get_object_for_this_type(slot=self)
        else:
            return None
    
    def assign(self, content, old_content=None):
        if old_content is not None:
            old_content.slot = None
            old_content.save()
        content.slot = self
        content.save()
        self.kind = ContentType.objects.get_for_model(content)
        self.save()
    
    def unassign(self):
        content = self.content()
        content.slot = None
        content.save()
        self.kind = None
        self.save()
    
    class Meta:
        ordering = ["start"]
    
    def __unicode__(self):
        start = localtime_for_timezone(self.start, settings.SCHEDULE_TIMEZONE)
        end = localtime_for_timezone(self.end, settings.SCHEDULE_TIMEZONE)
        
        if self.title:
            return u"%s (%s: %s — %s)" % (self.title, start.strftime("%a"), start.strftime("%X"), end.strftime("%X"))
        else:
            return u"%s: %s — %s" % (start.strftime("%a"), start.strftime("%X"), end.strftime("%X"))


class SpeakerSlotBase(models.Model):
    
    last_updated = models.DateTimeField(default=datetime.datetime.now, editable=False)
    
    def save(self, *args, **kwargs):
        self.last_updated = datetime.datetime.now()
        return super(SpeakerSlotBase, self).save(*args, **kwargs)
    
    def speakers(self):
        yield self.speaker
        for speaker in self.additional_speakers.all():
            yield speaker
    
    class Meta:
        abstract = True


class Presentation(SpeakerSlotBase):
    
    AUDIENCE_LEVEL_NOVICE = 1
    AUDIENCE_LEVEL_EXPERIENCED = 2
    AUDIENCE_LEVEL_INTERMEDIATE = 3
    
    AUDIENCE_LEVELS = [
        (AUDIENCE_LEVEL_NOVICE, "Novice"),
        (AUDIENCE_LEVEL_INTERMEDIATE, "Intermediate"),
        (AUDIENCE_LEVEL_EXPERIENCED, "Experienced"),
    ]
    
    DURATION_CHOICES = [
        (0, "No preference"),
        (1, "I prefer a 30 minute slot"),
        (2, "I prefer a 45 minute slot"),
    ]
    
    slot = models.OneToOneField(Slot, null=True, blank=True, related_name="presentation")
    
    title = models.CharField(max_length=100)
    description = models.TextField(
        max_length = 400, # @@@ need to enforce 400 in UI
        help_text = "Brief one paragraph blurb (will be public if accepted). Must be 400 characters or less"
    )
    kind = models.ForeignKey(PresentationKind)
    category = models.ForeignKey(PresentationCategory)
    abstract = MarkupField(
        help_text = "More detailed description (will be public if accepted).",
    )
    audience_level = models.IntegerField(choices=AUDIENCE_LEVELS)
    duration = models.IntegerField(choices=DURATION_CHOICES)
    
    submitted = models.DateTimeField(
        default = datetime.datetime.now,
        editable = False,
    )
    speaker = models.ForeignKey("speakers.Speaker", related_name="sessions")
    additional_speakers = models.ManyToManyField("speakers.Speaker", blank=True)
    cancelled = models.BooleanField(default=False)
    released = models.BooleanField(default=False)
    
    extreme_pycon = models.BooleanField(u"EXTREME PyCon!", default=False)
    invited = models.BooleanField(default=False)
    
    def get_absolute_url(self):
        return reverse("schedule_presentation", args=[self.pk])
    
    def __unicode__(self):
        return u"%s" % self.title


class Plenary(SpeakerSlotBase):
    
    slot = models.OneToOneField(Slot, null=True, blank=True, related_name="plenary")
    title = models.CharField(max_length=100)
    speaker = models.ForeignKey("speakers.Speaker", null=True, blank=True, related_name="+")
    additional_speakers = models.ManyToManyField("speakers.Speaker", blank=True)
    description = models.TextField(max_length=400, blank=True)


class Recess(models.Model):
    """
    We call this recess due to Break resulting in using break (lower-case "b")
    which is a Python keyword.
    """
    
    slot = models.OneToOneField(Slot, null=True, blank=True, related_name="recess")
    title = models.CharField(max_length=100)
    description = models.TextField(max_length=400, blank=True)


class UserBookmark(models.Model):
    
    user = models.ForeignKey(User)
    presentation = models.ForeignKey(Presentation)
    
    class Meta:
        unique_together = [("user", "presentation")]
