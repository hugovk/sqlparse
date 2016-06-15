# -*- coding: utf-8 -*-
#
# Copyright (C) 2016 Andi Albrecht, albrecht.andi@gmail.com
#
# This module is part of python-sqlparse and is released under
# the BSD License: http://www.opensource.org/licenses/bsd-license.php

from sqlparse import sql
from sqlparse import tokens as T
from sqlparse.utils import recurse, imt

T_NUMERICAL = (T.Number, T.Number.Integer, T.Number.Float)
T_STRING = (T.String, T.String.Single, T.String.Symbol)
T_NAME = (T.Name, T.Name.Placeholder)


def _group_matching(tlist, cls):
    """Groups Tokens that have beginning and end."""
    opens = []
    for token in list(tlist):
        if token.is_group() and not isinstance(token, cls):
            # Check inside previously grouped (ie. parenthesis) if group
            # of differnt type is inside (ie, case). though ideally  should
            # should check for all open/close tokens at once to avoid recursion
            _group_matching(token, cls)
            continue

        if token.match(*cls.M_OPEN):
            opens.append(token)
        elif token.match(*cls.M_CLOSE):
            try:
                open_token = opens.pop()
            except IndexError:
                # this indicates invalid sql and unbalanced tokens.
                # instead of break, continue in case other "valid" groups exist
                continue
            oidx = tlist.token_index(open_token)
            cidx = tlist.token_index(token)
            tlist.group_tokens(cls, oidx, cidx)


def group_brackets(tlist):
    _group_matching(tlist, sql.SquareBrackets)


def group_parenthesis(tlist):
    _group_matching(tlist, sql.Parenthesis)


def group_case(tlist):
    _group_matching(tlist, sql.Case)


def group_if(tlist):
    _group_matching(tlist, sql.If)


def group_for(tlist):
    _group_matching(tlist, sql.For)


def group_begin(tlist):
    _group_matching(tlist, sql.Begin)


def _group_left_right(tlist, m, cls,
                      valid_left=lambda t: t is not None,
                      valid_right=lambda t: t is not None,
                      semicolon=False):
    """Groups together tokens that are joined by a middle token. ie. x < y"""
    for token in list(tlist):
        if token.is_group() and not isinstance(token, cls):
            _group_left_right(token, m, cls, valid_left, valid_right,
                              semicolon)
            continue
        if not token.match(*m):
            continue

        tidx = tlist.token_index(token)
        pidx, prev_ = tlist.token_prev(tidx)
        nidx, next_ = tlist.token_next(tidx)

        if valid_left(prev_) and valid_right(next_):
            if semicolon:
                # only overwrite if a semicolon present.
                m_semicolon = T.Punctuation, ';'
                snidx, _ = tlist.token_next_by(m=m_semicolon, idx=nidx)
                nidx = snidx or nidx
            # Luckily, this leaves the position of `token` intact.
            tlist.group_tokens(cls, pidx, nidx, extend=True)


def group_typecasts(tlist):
    _group_left_right(tlist, (T.Punctuation, '::'), sql.Identifier)


def group_period(tlist):
    lfunc = lambda tk: imt(tk, i=(sql.SquareBrackets, sql.Identifier),
                           t=(T.Name, T.String.Symbol,))

    rfunc = lambda tk: imt(tk, i=(sql.SquareBrackets, sql.Function),
                           t=(T.Name, T.String.Symbol, T.Wildcard))

    _group_left_right(tlist, (T.Punctuation, '.'), sql.Identifier,
                      valid_left=lfunc, valid_right=rfunc)


def group_as(tlist):
    lfunc = lambda tk: not imt(tk, t=T.Keyword) or tk.normalized == 'NULL'
    rfunc = lambda tk: not imt(tk, t=(T.DML, T.DDL))
    _group_left_right(tlist, (T.Keyword, 'AS'), sql.Identifier,
                      valid_left=lfunc, valid_right=rfunc)


def group_assignment(tlist):
    _group_left_right(tlist, (T.Assignment, ':='), sql.Assignment,
                      semicolon=True)


def group_comparison(tlist):
    I_COMPERABLE = (sql.Parenthesis, sql.Function, sql.Identifier,
                    sql.Operation)
    T_COMPERABLE = T_NUMERICAL + T_STRING + T_NAME

    func = lambda tk: (imt(tk, t=T_COMPERABLE, i=I_COMPERABLE) or
                       (tk and tk.is_keyword and tk.normalized == 'NULL'))

    _group_left_right(tlist, (T.Operator.Comparison, None), sql.Comparison,
                      valid_left=func, valid_right=func)


@recurse(sql.Identifier)
def group_identifier(tlist):
    T_IDENT = (T.String.Symbol, T.Name)

    tidx, token = tlist.token_next_by(t=T_IDENT)
    while token:
        tlist.group_tokens(sql.Identifier, tidx, tidx)
        tidx, token = tlist.token_next_by(t=T_IDENT, idx=tidx)


def group_arrays(tlist):
    tidx, token = tlist.token_next_by(i=sql.SquareBrackets)
    while token:
        pidx, prev_ = tlist.token_prev(tidx)
        if imt(prev_, i=(sql.SquareBrackets, sql.Identifier, sql.Function),
               t=(T.Name, T.String.Symbol,)):
            tlist.group_tokens(sql.Identifier, pidx, tidx, extend=True)
            tidx = pidx
        tidx, token = tlist.token_next_by(i=sql.SquareBrackets, idx=tidx)


@recurse(sql.Identifier)
def group_operator(tlist):
    ttypes = T_NUMERICAL + T_STRING + T_NAME
    clss = (sql.SquareBrackets, sql.Parenthesis, sql.Function,
               sql.Identifier, sql.Operation)

    def match(token):
        return imt(token, t=(T.Operator, T.Wildcard))

    def valid(token):
        return imt(token, i=clss, t=ttypes)

    def post(tlist, pidx, tidx, nidx):
        tlist[tidx].ttype = T.Operator
        return pidx, nidx

    _group(tlist, sql.Operation, match, valid, valid, post, extend=False)


def group_identifier_list(tlist):
    m_role = T.Keyword, ('null', 'role')
    m_comma = T.Punctuation, ','
    clss = (sql.Function, sql.Case, sql.Identifier, sql.Comparison,
            sql.IdentifierList, sql.Operation)
    ttypes = (T_NUMERICAL + T_STRING + T_NAME +
              (T.Keyword, T.Comment, T.Wildcard))

    def match(token):
        return imt(token, m=m_comma)

    def func(token):
        return imt(token, i=clss, m=m_role, t=ttypes)

    def post(tlist, pidx, tidx, nidx):
        return pidx, nidx

    _group(tlist, sql.IdentifierList, match,
           valid_left=func, valid_right=func, post=post, extend=True)


@recurse(sql.Comment)
def group_comments(tlist):
    tidx, token = tlist.token_next_by(t=T.Comment)
    while token:
        eidx, end = tlist.token_not_matching(
            lambda tk: imt(tk, t=T.Comment) or tk.is_whitespace(), idx=tidx)
        if end is not None:
            eidx, end = tlist.token_prev(eidx, skip_ws=False)
            tlist.group_tokens(sql.Comment, tidx, eidx)

        tidx, token = tlist.token_next_by(t=T.Comment, idx=tidx)


@recurse(sql.Where)
def group_where(tlist):
    tidx, token = tlist.token_next_by(m=sql.Where.M_OPEN)
    while token:
        eidx, end = tlist.token_next_by(m=sql.Where.M_CLOSE, idx=tidx)

        if end is None:
            end = tlist._groupable_tokens[-1]
        else:
            end = tlist.tokens[eidx - 1]
        # TODO: convert this to eidx instead of end token.
        # i think above values are len(tlist) and eidx-1
        eidx = tlist.token_index(end)
        tlist.group_tokens(sql.Where, tidx, eidx)
        tidx, token = tlist.token_next_by(m=sql.Where.M_OPEN, idx=tidx)


@recurse()
def group_aliased(tlist):
    I_ALIAS = (sql.Parenthesis, sql.Function, sql.Case, sql.Identifier,
               sql.Operation)

    tidx, token = tlist.token_next_by(i=I_ALIAS, t=T.Number)
    while token:
        nidx, next_ = tlist.token_next(tidx)
        if imt(next_, i=sql.Identifier):
            tlist.group_tokens(sql.Identifier, tidx, nidx, extend=True)
        tidx, token = tlist.token_next_by(i=I_ALIAS, t=T.Number, idx=tidx)


@recurse(sql.Function)
def group_functions(tlist):
    has_create = False
    has_table = False
    for tmp_token in tlist.tokens:
        if tmp_token.value == 'CREATE':
            has_create = True
        if tmp_token.value == 'TABLE':
            has_table = True
    if has_create and has_table:
        return

    tidx, token = tlist.token_next_by(t=T.Name)
    while token:
        nidx, next_ = tlist.token_next(tidx)
        if isinstance(next_, sql.Parenthesis):
            tlist.group_tokens(sql.Function, tidx, nidx)
        tidx, token = tlist.token_next_by(t=T.Name, idx=tidx)


def group_order(tlist):
    """Group together Identifier and Asc/Desc token"""
    tidx, token = tlist.token_next_by(t=T.Keyword.Order)
    while token:
        pidx, prev_ = tlist.token_prev(tidx)
        if imt(prev_, i=sql.Identifier, t=T.Number):
            tlist.group_tokens(sql.Identifier, pidx, tidx)
            tidx = pidx
        tidx, token = tlist.token_next_by(t=T.Keyword.Order, idx=tidx)


@recurse()
def align_comments(tlist):
    tidx, token = tlist.token_next_by(i=sql.Comment)
    while token:
        pidx, prev_ = tlist.token_prev(tidx)
        if isinstance(prev_, sql.TokenList):
            tlist.group_tokens(sql.TokenList, pidx, tidx, extend=True)
            tidx = pidx
        tidx, token = tlist.token_next_by(i=sql.Comment, idx=tidx)


def group(stmt):
    for func in [
        group_comments,

        # _group_matching
        group_brackets,
        group_parenthesis,
        group_case,
        group_if,
        group_for,
        group_begin,

        group_functions,
        group_where,
        group_period,
        group_arrays,
        group_identifier,
        group_operator,
        group_order,
        group_typecasts,
        group_as,
        group_aliased,
        group_assignment,
        group_comparison,

        align_comments,
        group_identifier_list,
    ]:
        func(stmt)
    return stmt


def _group(tlist, cls, match,
           valid_left=lambda t: True,
           valid_right=lambda t: True,
           post=None,
           extend=True):
    """Groups together tokens that are joined by a middle token. ie. x < y"""

    tidx_offset = 0
    pidx, prev_ = None, None
    for idx, token in enumerate(list(tlist)):
        tidx = idx - tidx_offset

        if token.is_whitespace():
            continue
        if token.is_group() and not isinstance(token, cls):
            _group(token, cls, match, valid_left, valid_right, post, extend)
            pidx, prev_ = tidx, token
            continue
        if not match(token):
            pidx, prev_ = tidx, token
            continue

        nidx, next_ = tlist.token_next(tidx)

        if valid_left(prev_) and valid_right(next_):
            from_idx, to_idx = post(tlist, pidx, tidx, nidx)
            grp = tlist.group_tokens(cls, from_idx, to_idx, extend=extend)
            tidx_offset += to_idx - from_idx
            pidx, prev_ = from_idx, grp
        else:
            pidx, prev_ = tidx, token
