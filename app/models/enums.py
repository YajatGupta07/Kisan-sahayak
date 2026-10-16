from enum import Enum


class CaseState(str, Enum):
    NEW = "NEW"
    INTAKE = "INTAKE"
    DEADLINE_CONFIRM = "DEADLINE_CONFIRM"
    GATHER = "GATHER"
    CROP_MISMATCH = "CROP_MISMATCH"
    REPORT_CONSENT = "REPORT_CONSENT"
    REPORTING = "REPORTING"
    REPORTED = "REPORTED"
    DEADLINE_MISSED_WITH_PROOF = "DEADLINE_MISSED_WITH_PROOF"
    AWAIT_SURVEY = "AWAIT_SURVEY"
    AWAIT_ASSESSMENT = "AWAIT_ASSESSMENT"
    AWAIT_YIELD_DATA = "AWAIT_YIELD_DATA"
    AWAIT_PAYMENT = "AWAIT_PAYMENT"
    DIAGNOSE = "DIAGNOSE"
    CLOSED_PAID = "CLOSED_PAID"
    CLOSED_NOT_PAYABLE = "CLOSED_NOT_PAYABLE"
    BLOCKED = "BLOCKED"


TERMINAL_STATES = {CaseState.CLOSED_PAID, CaseState.CLOSED_NOT_PAYABLE}


class ClaimType(str, Enum):
    LOCALISED = "LOCALISED"
    POST_HARVEST = "POST_HARVEST"
    WIDESPREAD = "WIDESPREAD"


class FactSource(str, Enum):
    FARMER = "farmer"
    PORTAL = "portal"
    RECORD = "record"
    LAND_RECORD = "land_record"
    WEATHER = "weather"
    INSURER = "insurer"
    BANK = "bank"
    AGENT_ESTIMATE = "agent_estimate"
    FIXTURE = "fixture"


# Sources that can close a case (never agent_estimate or farmer alone)
EXTERNAL_SOURCES = {FactSource.PORTAL, FactSource.RECORD, FactSource.INSURER, FactSource.BANK,
                    FactSource.LAND_RECORD, FactSource.FIXTURE}


class Channel(str, Enum):
    INSURER_APP = "insurer_app"
    HELPLINE = "helpline_14447"
    INSURER_OFFICE = "insurer_office"
    BANK_BRANCH = "bank_branch"
    CSC = "csc"


class ActionKind(str, Enum):
    CONFIRM_DEADLINE = "CONFIRM_DEADLINE"
    REPORT_LOSS = "REPORT_LOSS"
    GRIEVANCE = "GRIEVANCE"
    RTI = "RTI"
    ENROLMENT_CORRECTION = "ENROLMENT_CORRECTION"


class ActionStatus(str, Enum):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    DECLINED = "DECLINED"
    EXECUTED = "EXECUTED"
    FAILED = "FAILED"
    SUPERSEDED = "SUPERSEDED"


class Outcome(str, Enum):
    PAID = "PAID"
    BLOCKED = "BLOCKED"
    NOT_PAYABLE = "NOT_PAYABLE"
    DEADLINE_MISSED_WITH_PROOF = "DEADLINE_MISSED_WITH_PROOF"


class CheckKind(str, Enum):
    STATUS_POLL = "STATUS_POLL"
    YIELD_CHECK = "YIELD_CHECK"
    DEADLINE_WARNING = "DEADLINE_WARNING"
    REPORT_NOW = "REPORT_NOW"
    RETRY_REPORT = "RETRY_REPORT"


class Intent(str, Enum):
    CONFIRM = "CONFIRM"
    DENY = "DENY"
    CORRECTION = "CORRECTION"
    QUESTION = "QUESTION"
    INFO = "INFO"
