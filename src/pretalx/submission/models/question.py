from django.db import models
from django.urls import reverse
from django.utils.functional import cached_property
from django.utils.timezone import now
from django.utils.translation import gettext_lazy as _
from django_scopes import ScopedManager
from i18nfield.fields import I18nCharField

from pretalx.agenda.rules import is_agenda_visible
from pretalx.common.models.choices import Choices
from pretalx.common.models.mixins import OrderedModel, PretalxModel
from pretalx.common.text.path import path_with_hash
from pretalx.common.text.phrases import phrases
from pretalx.common.urls import EventUrls
from pretalx.event.rules import can_change_event_settings
from pretalx.person.rules import is_reviewer
from pretalx.submission.rules import is_cfp_open, orga_can_change_submissions


def answer_file_path(instance, filename):
    return path_with_hash(
        filename, base_path=f"{instance.question.event.slug}/question_uploads/"
    )


class QuestionManager(models.Manager):
    def get_queryset(self):
        return (
            super()
            .get_queryset()
            .exclude(active=False)
            .exclude(target=QuestionTarget.REVIEWER)
        )


class AllQuestionManager(models.Manager):
    pass


class QuestionVariant(Choices):
    NUMBER = "number"
    STRING = "string"
    TEXT = "text"
    URL = "url"
    DATE = "date"
    DATETIME = "datetime"
    BOOLEAN = "boolean"
    FILE = "file"
    CHOICES = "choices"
    MULTIPLE = "multiple_choice"

    short_answers = (NUMBER, STRING, URL, DATE, DATETIME, FILE, CHOICES, MULTIPLE)
    long_answers = (TEXT,)

    valid_choices = [
        (NUMBER, _("Number")),
        (STRING, _("Text (one-line)")),
        (TEXT, _("Multi-line text")),
        (URL, _("URL")),
        (DATE, _("Date")),
        (DATETIME, _("Date and time")),
        (BOOLEAN, _("Yes/No")),
        (FILE, _("File upload")),
        (CHOICES, _("Choose one from a list")),
        (MULTIPLE, _("Choose multiple from a list")),
    ]


class QuestionTarget(Choices):
    SUBMISSION = "submission"
    SPEAKER = "speaker"
    REVIEWER = "reviewer"

    valid_choices = [
        (SUBMISSION, _("per proposal")),
        (SPEAKER, _("per speaker")),
        (REVIEWER, _("for reviewers")),
    ]


class QuestionRequired(Choices):
    OPTIONAL = "optional"
    REQUIRED = "required"
    AFTER_DEADLINE = "after_deadline"

    valid_choices = [
        (OPTIONAL, _("always optional")),
        (REQUIRED, _("always required")),
        (AFTER_DEADLINE, _("required after a deadline")),
    ]


class QuestionIcon(Choices):
    DISCORD = "discord"
    GITHUB = "github"
    INSTAGRAM = "instagram"
    LINKEDIN = "linkedin"
    MASTODON = "mastodon"
    TWITTER = "twitter"
    WEB = "web"
    YOUTUBE = "youtube"

    valid_choices = [
        (DISCORD, _("Discord")),
        (GITHUB, _("GitHub")),
        (INSTAGRAM, _("Instagram")),
        (LINKEDIN, _("LinkedIn")),
        (MASTODON, _("Mastodon")),
        (TWITTER, _("Twitter")),
        (WEB, _("Website")),
        (YOUTUBE, _("YouTube")),
    ]


# Question and question option permissions should be in sync
QUESTION_PERMISSIONS = {
    "list": is_cfp_open | is_agenda_visible | orga_can_change_submissions | is_reviewer,
    "orga_list": orga_can_change_submissions,
    "view": is_cfp_open | is_agenda_visible | orga_can_change_submissions | is_reviewer,
    "orga_view": orga_can_change_submissions,
    "create": can_change_event_settings,
    "update": can_change_event_settings,
    "delete": can_change_event_settings,
}


class Question(OrderedModel, PretalxModel):
    """Questions can be asked per.

    :class:`~pretalx.submission.models.submission.Submission`, per speaker, or
    of reviewers per :class:`~pretalx.submission.models.review.Review`.

    Questions can have many types, which offers a flexible framework to give organisers
    the opportunity to get all the information they need.

    :param variant: Can be any of 'number', 'string', 'text', 'boolean',
        'file', 'choices', or 'multiple_choice'. Defined in the
        ``QuestionVariant`` class.
    :param target: Can be any of 'submission', 'speaker', or 'reviewer'.
        Defined in the ``QuestionTarget`` class.
    :param deadline: Datetime field. This field is required for 'after deadline' and 'freeze after' options of
        question_required field and optional for the other ones. For 'after deadline' it shows that the answer will
        be optional before the deadline and mandatory after that deadline. For 'freeze after' it shows that the
        answer will be allowed before the deadline and frozen after that deadline
    :param question_required: Can be any of 'none', 'require ', 'after deadline', or 'freeze after'.
        Defined in the ``QuestionRequired`` class.
        'required' answering this question will always be required.
        'optional' means that it will never be mandatory.
        'after deadline' the answer will be optional before the deadline and mandatory after the deadline.
    :param freeze_after: Can be a datetime field or null.
        For 'freeze after' the answer will be allowed before the deadline and frozen after the deadline.
    :param position: Position in the question order in this event.
    """

    event = models.ForeignKey(
        to="event.Event", on_delete=models.PROTECT, related_name="questions"
    )
    variant = models.CharField(
        max_length=QuestionVariant.get_max_length(),
        choices=QuestionVariant.get_choices(),
        default=QuestionVariant.STRING,
    )
    target = models.CharField(
        max_length=QuestionTarget.get_max_length(),
        choices=QuestionTarget.get_choices(),
        default=QuestionTarget.SUBMISSION,
        verbose_name=_("Field type"),
        help_text=_(
            "Do you require an answer from every speaker or for every session?"
        ),
    )
    deadline = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_("Deadline"),
        help_text=_("Set a deadline to make this field required after the given date."),
    )
    freeze_after = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_("freeze after"),
        help_text=_(
            "Set a deadline to stop changes to responses after the given date."
        ),
    )
    question_required = models.CharField(
        max_length=QuestionRequired.get_max_length(),
        choices=QuestionRequired.get_choices(),
        default=QuestionRequired.OPTIONAL,
        verbose_name=_("Field required"),
    )
    tracks = models.ManyToManyField(
        to="submission.Track",
        related_name="questions",
        help_text=_(
            "You can limit this field to some tracks. Leave empty to apply to all tracks."
        ),
        verbose_name=_("Tracks"),
        blank=True,
    )
    submission_types = models.ManyToManyField(
        to="submission.SubmissionType",
        related_name="questions",
        help_text=_(
            "You can limit this field to some session types. Leave empty to apply to all session types."
        ),
        verbose_name=_("Session Types"),
        blank=True,
    )
    question = I18nCharField(max_length=800, verbose_name=_("Label"))
    help_text = I18nCharField(
        null=True,
        blank=True,
        max_length=800,
        verbose_name=_("help text"),
        help_text=_("Will appear just like this text below the custom input field.")
        + " "
        + phrases.base.use_markdown,
    )
    default_answer = models.TextField(
        null=True, blank=True, verbose_name=_("default answer")
    )
    position = models.IntegerField(default=0)
    active = models.BooleanField(
        default=True,
        verbose_name=_("active"),
        help_text=_("Inactive fields will no longer be shown."),
    )
    contains_personal_data = models.BooleanField(
        default=True,
        verbose_name=_("Responses contain personal data"),
        help_text=_(
            "If a user deletes their account, responses containing personal data will be removed, too."
        ),
    )
    min_length = models.PositiveIntegerField(
        null=True,
        blank=True,
        verbose_name=_("Minimum text length"),
        help_text=_(
            "Minimum allowed text in characters or words (set in CfP settings)."
        ),
    )
    max_length = models.PositiveIntegerField(
        null=True,
        blank=True,
        verbose_name=_("Maximum text length"),
        help_text=_(
            "Maximum allowed text length in characters or words (set in CfP settings)."
        ),
    )
    min_number = models.DecimalField(
        decimal_places=6,
        max_digits=16,
        null=True,
        blank=True,
        verbose_name=_("Minimum value"),
    )
    max_number = models.DecimalField(
        decimal_places=6,
        max_digits=16,
        null=True,
        blank=True,
        verbose_name=_("Maximum value"),
    )
    min_date = models.DateField(
        null=True,
        blank=True,
        verbose_name=_("Minimum value"),
    )
    max_date = models.DateField(
        null=True,
        blank=True,
        verbose_name=_("Maximum value"),
    )
    min_datetime = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_("Minimum value"),
    )
    max_datetime = models.DateTimeField(
        null=True, blank=True, verbose_name=_("Maximum value")
    )
    is_public = models.BooleanField(
        default=False,
        verbose_name=_("Publish answers"),
        help_text=_(
            "Responses will be shown on session or speaker pages as appropriate. Please note that you cannot make a field public after the first answers have been given, to allow speakers explicit consent before publishing information."
        ),
    )
    is_visible_to_reviewers = models.BooleanField(
        default=True,
        verbose_name=_("Show answers to reviewers"),
        help_text=_(
            "Should responses to this field be shown to reviewers? This is helpful if you want to collect personal information, but use anonymous reviews."
        ),
    )
    icon = models.CharField(
        max_length=QuestionIcon.get_max_length(),
        choices=QuestionIcon.get_choices(),
        null=True,
        blank=True,
        verbose_name=_("Icon"),
        help_text=_(
            "Custom URL fields that are shown publicly can use an icon when displaying the link."
        ),
    )
    objects = ScopedManager(event="event", _manager_class=QuestionManager)
    all_objects = ScopedManager(event="event", _manager_class=AllQuestionManager)

    log_prefix = "pretalx.question"

    class Meta:
        ordering = ("position", "id")
        rules_permissions = QUESTION_PERMISSIONS

    @property
    def log_parent(self):
        return self.event

    @cached_property
    def required(self):
        _now = now()
        # Question should become optional in order to be frozen
        if self.read_only:
            return False
        if self.question_required == QuestionRequired.REQUIRED:
            return True
        if self.question_required == QuestionRequired.AFTER_DEADLINE:
            return self.deadline <= _now
        return False

    @property
    def read_only(self):
        return self.freeze_after and (self.freeze_after <= now())

    @cached_property
    def icon_url(self):
        if self.icon:
            return reverse(
                "api:question-icon", kwargs={"event": self.event.slug, "pk": self.pk}
            )

    class urls(EventUrls):
        base = "{self.event.cfp.urls.questions}{self.pk}/"
        edit = "{base}edit/"
        delete = "{base}delete/"
        toggle = "{self.event.cfp.urls.questions}{self.pk}/toggle/"

    def __str__(self):
        return str(self.question)

    @staticmethod
    def get_order_queryset(event):
        return event.questions(manager="all_objects").all()

    def missing_answers(
        self, filter_speakers: list = False, filter_talks: list = False
    ) -> int:
        """Returns how many answers are still missing or this question.

        This method only supports submission questions and speaker questions.
        For missing reviews, please use the get_missing_reviews method.

        :param filter_speakers: Apply only to these speakers.
        :param filter_talks: Apply only to these talks.
        """
        from pretalx.person.models import User
        from pretalx.submission.models import Submission

        answers = self.answers.all()
        filter_talks = filter_talks or Submission.objects.none()
        filter_speakers = filter_speakers or User.objects.none()
        if filter_speakers or filter_talks:
            answers = answers.filter(
                models.Q(person__in=filter_speakers)
                | models.Q(submission__in=filter_talks)
            )
        answer_count = answers.count()
        if self.target == QuestionTarget.SUBMISSION:
            submissions = filter_talks or self.event.submissions.all()
            return max(submissions.count() - answer_count, 0)
        if self.target == QuestionTarget.SPEAKER:
            users = filter_speakers or User.objects.filter(
                submissions__event_id=self.event.pk
            )
            return max(users.count() - answer_count, 0)
        return 0


class AnswerOption(PretalxModel):
    """Provides the possible answers for.

    :class:`~pretalx.submission.models.question.Question` objects of variant
    'choice' or 'multiple_choice'.
    """

    question = models.ForeignKey(
        to="submission.Question", on_delete=models.PROTECT, related_name="options"
    )
    answer = I18nCharField(verbose_name=_("Response"))
    position = models.IntegerField(default=0)

    objects = ScopedManager(event="question__event")
    log_prefix = "pretalx.question.option"

    class Meta:
        ordering = ("position", "id")
        rules_permissions = QUESTION_PERMISSIONS

    @cached_property
    def event(self):
        return self.question.event

    @property
    def log_parent(self):
        return self.question

    def __str__(self):
        """Used in choice forms."""
        return str(self.answer)


class Answer(PretalxModel):
    """Answers are connected to a.

    :class:`~pretalx.submission.models.question.Question`, and, depending on
    type, a :class:`~pretalx.person.models.user.User`, a
    :class:`~pretalx.submission.models.submission.Submission`, or a
    :class:`~pretalx.submission.models.review.Review`.
    """

    question = models.ForeignKey(
        to="submission.Question", on_delete=models.PROTECT, related_name="answers"
    )
    submission = models.ForeignKey(
        to="submission.Submission",
        on_delete=models.PROTECT,
        related_name="answers",
        null=True,
        blank=True,
    )
    person = models.ForeignKey(
        to="person.User",
        on_delete=models.PROTECT,
        related_name="answers",
        null=True,
        blank=True,
    )
    review = models.ForeignKey(
        to="submission.Review",
        on_delete=models.PROTECT,
        related_name="answers",
        null=True,
        blank=True,
    )
    answer = models.TextField()
    answer_file = models.FileField(upload_to=answer_file_path, null=True, blank=True)
    options = models.ManyToManyField(
        to="submission.AnswerOption", related_name="answers"
    )

    objects = ScopedManager(event="question__event")

    class Meta:
        rules_permissions = {
            # Getting the answer API right is even trickier than getting the
            # question API right. Questions and options follow the same logic:
            # if you can see or change the question, the same goes for the option.
            # Not so with answers: Not all answers to public questions are public,
            # for example, and answers to reviewer questions are visible to people
            # depending on both their role and the current review phase.
            # To escape this complexity, we restrict the entire endpoint to people
            # with "change_event_settings" permissions for now, and tackle this
            # properly if there is demand and a) funding or b) contributions.
            "api": can_change_event_settings
            & orga_can_change_submissions
        }

    @cached_property
    def event(self):
        return self.question.event

    @property
    def log_parent(self):
        return self.event

    def __str__(self):
        """Help when debugging."""
        return f"Answer(question={self.question.question}, answer={self.answer})"

    def remove(self, person=None, force=False):
        """Deletes an answer."""
        for option in self.options.all():
            option.answers.remove(self)
        self.delete()

    remove.alters_data = True

    @cached_property
    def boolean_answer(self):
        if self.answer == "True":
            return True
        if self.answer == "False":
            return False

    @property
    def answer_string(self):
        if self.question.variant in ("number", "string", "text", "url"):
            return self.answer or ""
        if self.question.variant == "boolean":
            if self.boolean_answer is True:
                return _("Yes")
            if self.boolean_answer is False:
                return _("No")
            return ""
        if self.question.variant == "file":
            return self.answer_file.url if self.answer_file else ""
        if self.question.variant in ("choices", "multiple_choice"):
            return ", ".join(str(option.answer) for option in self.options.all())

    @property
    def is_answered(self):
        return bool(self.answer_string)

    def log_action(self, *args, content_object=None, **kwargs):
        if not content_object:
            if self.question.target == QuestionTarget.SPEAKER:
                content_object = self.person
            elif self.question.target == QuestionTarget.SUBMISSION:
                content_object = self.submission
            elif self.question.target == QuestionTarget.REVIEWER:
                content_object = self.review
        return super().log_action(*args, content_object=content_object, **kwargs)
