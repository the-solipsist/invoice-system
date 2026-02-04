from pydantic import BaseModel, Field, RootModel
from typing import List, Optional, Union, Dict, Any
from enum import Enum

class InvTyp(str, Enum):
    R = "R"
    DE = "DE"
    SEWP = "SEWP"
    SEWOP = "SEWOP"
    CBW = "CBW"

class ExpTyp(str, Enum):
    WPAY = "WPAY"
    WOPAY = "WOPAY"

class ItmDet(BaseModel):
    rt: int
    txval: float
    iamt: float = 0.0
    camt: float = 0.0
    samt: float = 0.0
    csamt: float = 0.0

class B2BItem(BaseModel):
    num: int
    itm_det: ItmDet

class B2BInvoice(BaseModel):
    inum: str = Field(max_length=16)
    idt: str # DD-MM-YYYY
    val: float
    pos: str
    rchrg: str = "N"
    inv_typ: InvTyp = InvTyp.R
    itms: List[B2BItem]

class B2BEntry(BaseModel):
    ctin: str
    inv: List[B2BInvoice]

class ExpItem(BaseModel):
    rt: int
    txval: float
    iamt: float = 0.0
    csamt: float = 0.0

class ExpInvoice(BaseModel):
    itms: List[ExpItem]
    inum: str = Field(max_length=16)
    idt: str
    val: float

class ExpEntry(BaseModel):
    exp_typ: ExpTyp
    inv: List[ExpInvoice]

class HsnEntry(BaseModel):
    hsn_sc: str
    txval: float
    iamt: float = 0.0
    camt: float = 0.0
    samt: float = 0.0
    csamt: float = 0.0
    desc: str
    user_desc: str
    uqc: str = "NA"
    qty: float
    rt: int
    num: int

class HsnSection(BaseModel):
    hsn_b2b: List[HsnEntry] = []
    hsn_b2c: List[HsnEntry] = []

class Doc(BaseModel):
    num: int
    from_num: str = Field(alias="from")
    to_num: str = Field(alias="to")
    totnum: int
    cancel: int = 0
    net_issue: int

class DocDet(BaseModel):
    doc_num: int = 1
    docs: List[Doc]

class DocIssueSection(BaseModel):
    doc_det: List[DocDet]

class Gstr1Payload(BaseModel):
    gstin: str
    fp: str
    gt: Optional[float] = None
    cur_gt: Optional[float] = None
    version: str = "GSTR1_V1.0"
    hash_val: str = Field(alias="hash")
    b2b: Optional[List[B2BEntry]] = None
    exp: Optional[List[ExpEntry]] = None
    hsn: Optional[HsnSection] = None
    doc_issue: Optional[DocIssueSection] = None

    class Config:
        populate_by_name = True
