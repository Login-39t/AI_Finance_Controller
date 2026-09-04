"""Registration, login, refresh, logout, and who-am-I.

The endpoint shapes match what `fastapi-users` produces, so swapping to
it once Postgres lands is a wiring change rather than a client rewrite.

Two behaviours here are worth reading closely, because both are places
where the obvious implementation is wrong:

* **login does the same work whether or not the email exists.** A lookup
  miss still runs a password verification against a dummy hash, so the
  response time does not tell an attacker which addresses are registered.
* **refresh rotates and detects reuse.** Presenting a token that has
  already been consumed revokes every token descended from that login,
  because the alternative - assuming it was a benign retry - is exactly
  what makes a stolen refresh token valuable.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Cookie, Response, status
from ledgergraph_domain.enums import UserRole
from pydantic import BaseModel, EmailStr, Field

from ..auth import (
    AuthError,
    digest_refresh_token,
    hash_password,
    mint_access_token,
    needs_rehash,
    new_refresh_token,
    refresh_cookie_params,
    refresh_expiry,
    validate_password,
    verify_password,
)
from ..config import get_settings
from ..deps import CanAdmin, CanControl, CurrentUser
from ..dto import Wire
from ..errors import ApiError
from ..store import User, get_repository, new_audit

router = APIRouter(prefix="/v1/auth", tags=["auth"])

#: A valid Argon2 hash of a value nobody knows. Verified against when an
#: email does not exist, purely so the timing of a miss matches a hit.
_DUMMY_HASH = hash_password("timing-equalisation-not-a-credential")


# --------------------------------------------------------------------------
# Wire models
# --------------------------------------------------------------------------

class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1)
    fullName: str = Field(min_length=1, max_length=120)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1)


class RoleUpdateRequest(BaseModel):
    #: Typed as the enum, so a value outside the four roles is a 422 from
    #: validation rather than something the endpoint has to police itself.
    role: UserRole


class AdminCreateUserRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1)
    fullName: str = Field(min_length=1, max_length=120)
    #: An admin picks the role directly - unlike self-registration, which
    #: never accepts one. The enum bounds it to the four valid roles.
    role: UserRole


class UserDTO(Wire):
    id: str
    email: str
    fullName: str
    role: str
    isActive: bool


class TokenDTO(Wire):
    accessToken: str
    tokenType: str = "bearer"
    expiresIn: int
    user: UserDTO


def _user_dto(user: User) -> UserDTO:
    return UserDTO(
        id=user.user_id, email=user.email, fullName=user.full_name,
        role=user.role.value, isActive=user.is_active,
    )


async def _issue(response: Response, user: User) -> TokenDTO:
    """Mint an access token and plant a fresh refresh cookie."""
    repo = get_repository()
    token, expires_in = mint_access_token(
        user_id=user.user_id, email=user.email, role=user.role.value
    )
    plaintext, digest, family_id = new_refresh_token()
    await repo.store_refresh(
        user_id=user.user_id, digest=digest, family_id=family_id,
        expires_at=refresh_expiry(),
    )
    response.set_cookie(value=plaintext, **refresh_cookie_params())
    return TokenDTO(accessToken=token, expiresIn=expires_in, user=_user_dto(user))


# --------------------------------------------------------------------------
# Endpoints
# --------------------------------------------------------------------------

@router.post("/register", response_model=TokenDTO,
             status_code=status.HTTP_201_CREATED, summary="Create an account")
async def register(body: RegisterRequest, response: Response) -> TokenDTO:
    """Self-registration always produces an analyst.

    The role is not a field on this request at all, rather than a field
    that is validated and overridden. A privilege parameter that the
    server ignores is one refactor away from a privilege parameter the
    server honours.
    """
    repo = get_repository()

    try:
        validate_password(body.password, email=str(body.email))
    except AuthError as exc:
        raise ApiError(exc.code, str(exc),
                       status_code=status.HTTP_422_UNPROCESSABLE_ENTITY) from exc

    if await repo.find_user_by_email(str(body.email)) is not None:
        # An honest 409. Hiding it would be enumeration theatre: a
        # registration form has to tell the user the address is taken or
        # it cannot function, and login is where the timing matters.
        raise ApiError("EMAIL_TAKEN", "an account with this email already exists",
                       status_code=status.HTTP_409_CONFLICT)

    user = await repo.create_user(
        email=str(body.email), hashed_password=hash_password(body.password),
        full_name=body.fullName, role=UserRole.ANALYST,
    )
    await repo.add_audit(new_audit(
        entity_type="user", entity_id=user.user_id, action="registered",
        actor_type="user", actor_id=user.user_id, actor_name=user.email,
        actor_role=user.role.value,
        detail=f"account created with role {user.role.value}",
    ))
    return await _issue(response, user)


@router.post("/login", response_model=TokenDTO, summary="Exchange credentials for tokens")
async def login(body: LoginRequest, response: Response) -> TokenDTO:
    repo = get_repository()
    user = await repo.find_user_by_email(str(body.email))

    # Always verify something, so a miss and a wrong password cost the same.
    ok = verify_password(body.password, user.hashed_password if user else _DUMMY_HASH)

    if user is None or not ok or not user.is_active:
        raise ApiError("INVALID_CREDENTIALS", "email or password is incorrect",
                       status_code=status.HTTP_401_UNAUTHORIZED)

    if needs_rehash(user.hashed_password):
        # Parameters were raised since this hash was written. The plaintext
        # is in hand exactly once per login; this is the only chance to
        # upgrade it without asking the user to do anything.
        user.hashed_password = hash_password(body.password)

    user.last_login_at = datetime.now(UTC)
    return await _issue(response, user)


@router.post("/refresh", response_model=TokenDTO, summary="Rotate the refresh token")
async def refresh(
    response: Response,
    lg_refresh: Annotated[str | None, Cookie()] = None,
) -> TokenDTO:
    repo = get_repository()
    if not lg_refresh:
        raise ApiError("NO_REFRESH_COOKIE", "no refresh token was presented",
                       status_code=status.HTTP_401_UNAUTHORIZED)

    token = await repo.find_refresh(digest_refresh_token(lg_refresh))
    if token is None:
        raise ApiError("REFRESH_INVALID", "refresh token is not recognised",
                       status_code=status.HTTP_401_UNAUTHORIZED)

    if token.consumed_at is not None:
        # Reuse. Either a copy is in circulation or a client replayed;
        # there is no way to tell them apart here, and only one of the two
        # is benign, so the whole family dies and everyone re-authenticates.
        revoked = await repo.revoke_family(token.family_id)
        await repo.add_audit(new_audit(
            entity_type="user", entity_id=token.user_id,
            action="refresh_reuse_detected", actor_type="system",
            detail=(
                f"a consumed refresh token was presented again; "
                f"revoked {revoked} token(s) in family {token.family_id[:8]}"
            ),
        ))
        response.delete_cookie(key="lg_refresh", path="/v1/auth")
        raise ApiError(
            "REFRESH_REUSED",
            "this session was ended because a used refresh token was presented again",
            status_code=status.HTTP_401_UNAUTHORIZED,
        )

    if not token.is_live:
        raise ApiError("REFRESH_EXPIRED", "refresh token has expired or was revoked",
                       status_code=status.HTTP_401_UNAUTHORIZED)

    user = await repo.get_user(token.user_id)
    if user is None or not user.is_active:
        raise ApiError("ACCOUNT_UNAVAILABLE", "this account can no longer sign in",
                       status_code=status.HTTP_401_UNAUTHORIZED)

    await repo.consume_refresh(token)

    # Rotate inside the same family, so reuse of *any* ancestor still
    # takes the whole chain down.
    access, expires_in = mint_access_token(
        user_id=user.user_id, email=user.email, role=user.role.value
    )
    plaintext, digest, _ = new_refresh_token()
    await repo.store_refresh(
        user_id=user.user_id, digest=digest, family_id=token.family_id,
        expires_at=refresh_expiry(),
    )
    response.set_cookie(value=plaintext, **refresh_cookie_params())
    return TokenDTO(accessToken=access, expiresIn=expires_in, user=_user_dto(user))


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, summary="End the session")
async def logout(
    lg_refresh: Annotated[str | None, Cookie()] = None,
) -> Response:
    """Revoke the family and drop the cookie.

    Unauthenticated on purpose: logging out must work with an expired
    access token, which is precisely when a user reaches for it.
    """
    repo = get_repository()
    if lg_refresh:
        token = await repo.find_refresh(digest_refresh_token(lg_refresh))
        if token is not None:
            await repo.revoke_family(token.family_id)
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    response.delete_cookie(key="lg_refresh", path="/v1/auth")
    return response


@router.get("/me", response_model=UserDTO, summary="The current user")
async def me(user: CurrentUser) -> UserDTO:
    return _user_dto(user)


@router.get("/users", response_model=list[UserDTO], summary="List users (controller+)")
async def list_users(_: CanControl) -> list[UserDTO]:
    # Active accounts only. A deactivated user is a soft delete - the row
    # survives so the audit events it authored still resolve to a name, but
    # it has no place in a management list of who can sign in.
    return [_user_dto(u) for u in await get_repository().list_users() if u.is_active]


@router.post("/users", response_model=UserDTO,
             status_code=status.HTTP_201_CREATED, summary="Create a user (admin)")
async def create_user_as_admin(
    body: AdminCreateUserRequest, actor: CanAdmin
) -> UserDTO:
    """Create an account with a chosen role. Admin only.

    Distinct from `/register` on two counts: an admin names the role
    (self-registration never does), and no session is issued - this mints
    a user for *someone else*, so it must not plant a refresh cookie that
    would replace the admin's own session with the new account's.
    """
    repo = get_repository()

    try:
        validate_password(body.password, email=str(body.email))
    except AuthError as exc:
        raise ApiError(exc.code, str(exc),
                       status_code=status.HTTP_422_UNPROCESSABLE_ENTITY) from exc

    if await repo.find_user_by_email(str(body.email)) is not None:
        raise ApiError("EMAIL_TAKEN", "an account with this email already exists",
                       status_code=status.HTTP_409_CONFLICT)

    user = await repo.create_user(
        email=str(body.email), hashed_password=hash_password(body.password),
        full_name=body.fullName, role=body.role,
    )
    await repo.add_audit(new_audit(
        entity_type="user", entity_id=user.user_id, action="registered",
        actor_type="user", actor_id=actor.user_id, actor_name=actor.email,
        actor_role=actor.role.value,
        detail=f"account created with role {user.role.value} by {actor.email}",
    ))
    return _user_dto(user)


@router.patch("/users/{user_id}", response_model=UserDTO,
              summary="Change a user's role (admin)")
async def set_user_role(
    user_id: str, body: RoleUpdateRequest, actor: CanAdmin
) -> UserDTO:
    """Grant or change a user's role. Admin only.

    This is what turns a self-registered analyst into a controller
    without touching the database. Two guards matter:

    * an admin cannot change *their own* role, because demoting the only
      admin would lock every account out of user management, with no
      endpoint left to undo it - a second admin must do that;
    * an unchanged role is an idempotent no-op that writes no audit event,
      so re-applying the same role does not litter the trail.
    """
    repo = get_repository()
    target = await repo.get_user(user_id)
    if target is None:
        raise ApiError("USER_NOT_FOUND", "no user with that id",
                       status_code=status.HTTP_404_NOT_FOUND)

    if target.user_id == actor.user_id and body.role is not actor.role:
        raise ApiError(
            "CANNOT_CHANGE_OWN_ROLE",
            "an admin cannot change their own role; ask another admin",
            status_code=status.HTTP_409_CONFLICT,
        )

    if target.role is body.role:
        return _user_dto(target)

    previous = target.role
    updated = await repo.update_user_role(user_id, body.role)
    assert updated is not None  # existence was checked above
    await repo.add_audit(new_audit(
        entity_type="user", entity_id=updated.user_id, action="role_changed",
        actor_type="user", actor_id=actor.user_id, actor_name=actor.email,
        actor_role=actor.role.value,
        detail=(f"role changed from {previous.value} to {body.role.value} "
                f"by {actor.email}"),
    ))
    return _user_dto(updated)


@router.post("/users/{user_id}/deactivate", response_model=UserDTO,
             summary="Deactivate a user (admin)")
async def deactivate_user(user_id: str, actor: CanAdmin) -> UserDTO:
    """Soft-delete an account. Admin only.

    A deactivated user cannot sign in (`login` and `refresh` both refuse an
    inactive account) and drops off the Users list, but the row is kept -
    hard-deleting it would orphan the audit events it authored, and an
    audit trail with holes in it is worse than none. Reactivation is
    deliberately not exposed here; restoring an account is a database
    operation, not a button, so a mis-click cannot silently let someone
    back in.

    Two guards:

    * an admin cannot deactivate *themselves* - the last admin locking
      their own account out would leave no one able to manage users;
    * an already-inactive account is an idempotent no-op that writes no
      second audit event.
    """
    repo = get_repository()
    target = await repo.get_user(user_id)
    if target is None:
        raise ApiError("USER_NOT_FOUND", "no user with that id",
                       status_code=status.HTTP_404_NOT_FOUND)

    if target.user_id == actor.user_id:
        raise ApiError(
            "CANNOT_DEACTIVATE_SELF",
            "an admin cannot deactivate their own account; ask another admin",
            status_code=status.HTTP_409_CONFLICT,
        )

    if not target.is_active:
        return _user_dto(target)

    updated = await repo.set_user_active(user_id, False)
    assert updated is not None  # existence was checked above
    await repo.add_audit(new_audit(
        entity_type="user", entity_id=updated.user_id, action="deactivated",
        actor_type="user", actor_id=actor.user_id, actor_name=actor.email,
        actor_role=actor.role.value,
        detail=f"account {updated.email} deactivated by {actor.email}",
    ))
    return _user_dto(updated)


# --------------------------------------------------------------------------
# Demo accounts
# --------------------------------------------------------------------------

#: One account per role, so the RBAC boundary can be demonstrated rather
#: than described. Seeded only when `seed_demo_users` is on, which
#: `config.py` refuses outside local and staging.
DEMO_USERS: tuple[tuple[str, str, UserRole], ...] = (
    ("analyst@tallyproof.dev", "Asha Analyst", UserRole.ANALYST),
    ("reviewer@tallyproof.dev", "Ravi Reviewer", UserRole.REVIEWER),
    ("controller@tallyproof.dev", "Chitra Controller", UserRole.CONTROLLER),
    ("admin@tallyproof.dev", "Arun Admin", UserRole.ADMIN),
)


async def seed_demo_users() -> int:
    """Create the four demo accounts if they are absent. Idempotent."""
    settings = get_settings()
    if not settings.seed_demo_users:
        return 0

    repo = get_repository()
    created = 0
    for email, name, role in DEMO_USERS:
        if await repo.find_user_by_email(email) is not None:
            continue
        await repo.create_user(
            email=email, hashed_password=hash_password(settings.demo_password),
            full_name=name, role=role,
        )
        created += 1
    return created


async def bootstrap_admin() -> str | None:
    """Promote the configured account to admin, once, at startup.

    The chicken-and-egg a production deploy would otherwise hit: user
    management needs an admin, but production seeds none and
    `/auth/register` only mints analysts. Setting `BOOTSTRAP_ADMIN_EMAIL`
    to an account that has registered closes it - that account becomes an
    admin on the next start, and can then grant roles through the API
    instead of raw SQL.

    Idempotent and safe to leave set: returns the email only when a
    promotion actually happened, and `None` when the variable is unset,
    the account has not registered yet, or it is already an admin.
    """
    settings = get_settings()
    email = (settings.bootstrap_admin_email or "").strip().lower()
    if not email:
        return None

    repo = get_repository()
    user = await repo.find_user_by_email(email)
    if user is None or user.role is UserRole.ADMIN:
        return None

    previous = user.role
    await repo.update_user_role(user.user_id, UserRole.ADMIN)
    await repo.add_audit(new_audit(
        entity_type="user", entity_id=user.user_id, action="role_changed",
        actor_type="system",
        detail=(f"promoted {email} from {previous.value} to admin "
                "via BOOTSTRAP_ADMIN_EMAIL"),
    ))
    return email
