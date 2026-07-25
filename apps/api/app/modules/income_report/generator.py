"""Генериране на XML файла SPR73_6 за Справката по чл. 73, ал. 6 от ЗДДФЛ.

Форматът следва схемата SPR73_6.xsd на НАП: кодиране WINDOWS-1251, име на файла
SPR73_6.xml, само положителни стойности (с изключение на поле diff18). Редът на
елементите съответства на реда в спецификацията.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from decimal import Decimal

from app.modules.income_report.schemas import (
    Chl736IncomeLine,
    Chl736Person,
    Chl736Report,
    Chl736TaxBase49,
)

ENCODING = "windows-1251"


def _num(value: Decimal | None) -> str:
    return f"{Decimal(value):.2f}"


def _sub(parent: ET.Element, tag: str, value) -> ET.Element:
    e = ET.SubElement(parent, tag)
    e.text = str(value)
    return e


def _opt_num(parent: ET.Element, tag: str, value: Decimal | None) -> None:
    """Добавя елемент само ако стойността е попълнена (незадължителни полета)."""
    if value is not None:
        _sub(parent, tag, _num(value))


def _income_line(parent: ET.Element, line: Chl736IncomeLine) -> None:
    row = ET.SubElement(parent, "rowsenum")
    _sub(row, "incomecode", line.incomecode)
    _sub(row, "employereik", line.employereik)
    _sub(row, "employername", line.employername)
    _sub(row, "income", _num(line.income))
    _opt_num(row, "healthinsbg", line.healthinsbg)
    _opt_num(row, "healthinsforeign", line.healthinsforeign)
    _sub(row, "advancetax", _num(line.advancetax))
    _opt_num(row, "taxreductiondisabled", line.taxreductiondisabled)
    _opt_num(row, "taxreductionins", line.taxreductionins)
    _opt_num(row, "taxreductionhealthins", line.taxreductionhealthins)
    if line.eiktransfrom is not None:
        _sub(row, "eiktransfrom", line.eiktransfrom)


def _taxbase49(parent: ET.Element, tb: Chl736TaxBase49) -> None:
    node = ET.SubElement(parent, "taxbase49")
    _opt_num(node, "taxbase", tb.taxbase)
    _opt_num(node, "taxreductiondisabled", tb.taxreductiondisabled)
    _opt_num(node, "taxreductionins", tb.taxreductionins)
    _opt_num(node, "taxreductionhealthins", tb.taxreductionhealthins)
    _opt_num(node, "taxreductionretire", tb.taxreductionretire)
    _opt_num(node, "taxreductiondonation01", tb.taxreductiondonation01)
    _opt_num(node, "taxreductiondonation02", tb.taxreductiondonation02)
    _opt_num(node, "taxreductiondonation03", tb.taxreductiondonation03)
    _opt_num(node, "taxreductionchildren", tb.taxreductionchildren)
    _opt_num(node, "taxreductionchildrendisab", tb.taxreductionchildrendisab)
    _opt_num(node, "taxbase491", tb.taxbase491)
    _opt_num(node, "tax", tb.tax)
    _opt_num(node, "diff18", tb.diff18)
    _opt_num(node, "sum19deducted", tb.sum19deducted)
    _opt_num(node, "sum19refund", tb.sum19refund)


def _person(parent: ET.Element, person: Chl736Person) -> None:
    row = ET.SubElement(parent, "rowsenum")
    _sub(row, "correctioncode", person.correctioncode)
    _sub(row, "firstname", person.firstname)
    if person.secondname is not None:
        _sub(row, "secondname", person.secondname)
    _sub(row, "thirdname", person.thirdname)
    _sub(row, "identtype", person.identtype)
    _sub(row, "ident", person.ident)
    _sub(row, "ismainemployer", person.ismainemployer)

    incomedata = ET.SubElement(row, "incomedata")
    incomerows = ET.SubElement(incomedata, "incomerows")
    for line in person.income_lines:
        _income_line(incomerows, line)
    _opt_num(incomedata, "taxbase251", person.taxbase251)
    _opt_num(incomedata, "taxbase253", person.taxbase253)
    if person.taxbase49 is not None:
        _taxbase49(incomedata, person.taxbase49)
    _sub(incomedata, "sumtaxdeducted", _num(person.sumtaxdeducted))


def build_xml(report: Chl736Report) -> bytes:
    """Сглобява целия документ dec736 и връща байтове в кодиране WINDOWS-1251."""
    root = ET.Element("dec736")
    if report.isterm is not None:
        _sub(root, "isterm", report.isterm)
    _sub(root, "year", report.year)

    payer = report.payer
    p1 = ET.SubElement(root, "part1")
    _sub(p1, "eik", payer.eik)
    _sub(p1, "name", payer.name)
    if payer.phone is not None:
        _sub(p1, "phone", payer.phone)
    if payer.mail is not None:
        _sub(p1, "mail", payer.mail)
    if payer.reprname is not None:
        _sub(p1, "reprname", payer.reprname)
    if payer.reprident is not None:
        _sub(p1, "reprident", payer.reprident)

    p2 = ET.SubElement(root, "part2")
    for person in report.persons:
        _person(p2, person)

    body = ET.tostring(root, encoding="unicode")
    xml = f'<?xml version="1.0" encoding="WINDOWS-1251"?>\n{body}'
    return xml.encode(ENCODING, errors="replace")
