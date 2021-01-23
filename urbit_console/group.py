#!python3

from __future__ import annotations

import attr, re, enum

from typing import Set, Dict, Union, Any

def normalize_patp(inp: str) -> str:
    if inp.startswith('~'):
        inp = inp[1:]
    # detect galaxy names
    if inp.isalpha() and inp.islower() and len(inp) == 3:
        return inp
    o = re.match(r"^([a-z]{6}-{1,2})+[a-z]{6}$", inp)
    if o is not None:
        return inp
    raise ValueError(f"invalid @p: {inp}")

@attr.s(auto_attribs=True, frozen=True)
class Ship:
    # a day may come when I properly parse @p in Python, but it is not this day
    name: str = attr.ib(converter=normalize_patp)

class RoleTag(enum.Enum):
    Admin = 1
    Moderator = 2
    Janitor = 3

@attr.s(auto_attribs=True, frozen=True)
class AppTag:
    app: str
    tag: str

class Rank(enum.Enum):
    Galaxy = 1
    Star = 2
    Planet = 3
    Moon = 4
    Comet = 5

@attr.s(auto_attribs=True)
class OpenPolicy:
    banned_ranks: Set[Rank]
    banned_ships: Set[Ship]

@attr.s(auto_attribs=True)
class InvitePolicy:
    pending_invites: Set[Ship]

@attr.s(auto_attribs=True)
class Group:
    members: Set[Ship]
    tags: Dict[Union[RoleTag, AppTag], Set[Ship]]
    policy: Union[OpenPolicy, InvitePolicy]
    hidden: bool

    @classmethod
    def from_dict(cls, inp: Dict[str, Any]) -> Group:
        tags = {}
        for k, v in inp['tags'].items():
            if k in ['admin', 'moderator', 'janitor']:
                tag = RoleTag[k.capitalize()]
                tags[tag] = set(Ship(name=i) for i in v)
            else:
                for nk, nv in v.items():
                    tag = AppTag(app=k, tag=nk)
                    tags[tag] = set(Ship(name=i) for i in nv)

        members = set(Ship(name=i) for i in inp['members'])

        p = inp['policy']
        if 'open' in p:
            pol = OpenPolicy(
                banned_ranks=set(),
                banned_ships=set(Ship(name=i) for i in p['open']['banned']))
        # TODO handle invite policies
        else:
            raise ValueError("unknown policy")

        return cls(members=members, tags=tags, policy=pol,
                   hidden=inp['hidden'])

@attr.s(auto_attribs=True, frozen=True)
class Resource:
    ship: Ship
    name: str

    @classmethod
    def from_str(cls, inp: str) -> Resource:
        if not inp.startswith("/ship/"):
            raise ValueError(f"invalid resource literal '{inp}'")
        _, _, p, n = inp.split('/')
        return cls(ship=Ship(name=p), name=n)

@attr.s(auto_attribs=True)
class AllGroups:
    groups: Dict[Resource, Group]

    @classmethod
    def from_dict(cls, inp: Dict[str, Any]) -> AllGroups:
        d = {}
        for k in inp:
            r = Resource.from_str(k)
            d[r] = Group.from_dict(inp[k])
        return cls(groups=d)
