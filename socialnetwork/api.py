from django.db.models import Q, Exists, OuterRef, When, IntegerField, FloatField, Count, ExpressionWrapper, Case, Value, F, Prefetch

from fame.models import Fame, FameLevels, FameUsers, ExpertiseAreas
from socialnetwork.models import Posts, SocialNetworkUsers


# general methods independent of html and REST views
# should be used by REST and html views


def _get_social_network_user(user) -> SocialNetworkUsers:
    """Given a FameUser, gets the social network user from the request. Assumes that the user is authenticated."""
    try:
        user = SocialNetworkUsers.objects.get(id=user.id)
    except SocialNetworkUsers.DoesNotExist:
        raise PermissionError("User does not exist")
    return user


# ---------------------------------------------------------------------------
# T4 — Community Timeline
# ---------------------------------------------------------------------------

def timeline(user: SocialNetworkUsers, start: int = 0, end: int = None, published=True, community_mode=False):
    """Get the timeline of the user. Assumes that the user is authenticated."""

    if community_mode:
        # T4
        # in community mode, posts of communities are displayed if ALL of the following criteria are met:
        # 1. the author of the post is a member of the community
        # 2. the user is a member of the community
        # 3. the post contains the community's expertise area
        # 4. the post is published or the user is the author

        # Communities des Users holen
        user_communities = user.communities.all()

        if community_mode:

            # ------------------------------------------------------------------ #
            # T4 — Community Timeline Filter
            # ------------------------------------------------------------------ #

            # First we define a sub-query (not yet executed).
            # For each post (referenced via OuterRef) in the outer query, check whether there EXISTS
            # an ExpertiseArea that satisfies ALL three conditions:
            #   1. The post is classified under this ExpertiseArea (classified_as = relation between ExpertiseAreas and Posts)
            #   2. The post's author is a member of this ExpertiseArea's community
            #   3. The currently logged-in user is also a member of this ExpertiseArea (pk = primary key must be in the user's community IDs)
            valid_shared_community = Exists(
                ExpertiseAreas.objects.filter(
                    classified_as=OuterRef('pk'),
                    socialnetworkusers=OuterRef('author'),
                    pk__in=user.communities.values('pk'),
                )
            )

            # Here we select posts with a valid shared community (using the previous sub-query) and check
            # whether the post is published or the author is the user.
            posts = Posts.objects.filter(
                valid_shared_community
            ).filter(
                Q(published=published) | Q(author=user) # Q = OR
            ).order_by("-submitted")
    else:
        # in standard mode, posts of followed users are displayed
        _follows = user.follows.all()
        posts = Posts.objects.filter(
            (Q(author__in=_follows) & Q(published=published)) | Q(author=user)
        ).order_by("-submitted")
    if end is None:
        return posts[start:]
    else:
        return posts[start:end + 1]


def search(keyword: str, start: int = 0, end: int = None, published=True):
    """Search for all posts in the system containing the keyword. Assumes that all posts are public"""
    posts = Posts.objects.filter(
        Q(content__icontains=keyword)
        | Q(author__email__icontains=keyword)
        | Q(author__first_name__icontains=keyword)
        | Q(author__last_name__icontains=keyword),
        published=published,
    ).order_by("-submitted")
    if end is None:
        return posts[start:]
    else:
        return posts[start:end + 1]


def follows(user: SocialNetworkUsers, start: int = 0, end: int = None):
    """Get the users followed by this user. Assumes that the user is authenticated."""
    _follows = user.follows.all()
    if end is None:
        return _follows[start:]
    else:
        return _follows[start:end + 1]


def followers(user: SocialNetworkUsers, start: int = 0, end: int = None):
    """Get the followers of this user. Assumes that the user is authenticated."""
    _followers = user.followed_by.all()
    if end is None:
        return _followers[start:]
    else:
        return _followers[start:end + 1]


def follow(user: SocialNetworkUsers, user_to_follow: SocialNetworkUsers):
    """Follow a user. Assumes that the user is authenticated. If user already follows the user, signal that."""
    if user_to_follow in user.follows.all():
        return {"followed": False}
    user.follows.add(user_to_follow)
    user.save()
    return {"followed": True}


def unfollow(user: SocialNetworkUsers, user_to_unfollow: SocialNetworkUsers):
    """Unfollow a user. Assumes that the user is authenticated. If user does not follow the user anyway, signal that."""
    if user_to_unfollow not in user.follows.all():
        return {"unfollowed": False}
    user.follows.remove(user_to_unfollow)
    user.save()
    return {"unfollowed": True}

# ---------------------------------------------------------------------------
# T1 / T2 / T4 — Post Submission
# ---------------------------------------------------------------------------

def submit_post(
        user: SocialNetworkUsers,
        content: str,
        cites: Posts = None,
        replies_to: Posts = None,
):
    """Submit a post for publication. Assumes that the user is authenticated.
    returns a tuple of three elements:
    1. a dictionary with the keys "published" and "id" (the id of the post)
    2. a list of dictionaries containing the expertise areas and their truth ratings
    3. a boolean indicating whether the user was banned and logged out and should be redirected to the login page
    """

    # create post  instance:
    post = Posts.objects.create(
        content=content,
        author=user,
        cites=cites,
        replies_to=replies_to,
    )

    # classify the content into expertise areas:
    # only publish the post if none of the expertise areas contains bullshit:
    _at_least_one_expertise_area_contains_bullshit, _expertise_areas = (
        post.determine_expertise_areas_and_truth_ratings()
    )
    post.published = not _at_least_one_expertise_area_contains_bullshit

    redirect_to_logout = False

    # ------------------------------------------------------------------ #
    #       T1 —  not publish posts that have an expertise area
    # which is contained in the user’s fame profile and marked negative there
    # ------------------------------------------------------------------ #

    # _expertise_areas_ contains additional data like truth rating
    # Only collect the IDs (primary key) of all expertise areas this post is assigned to.
    expertise_area_ids = [
        entry["expertise_area"].id
        for entry in _expertise_areas
    ]

    # Unpublish the post if the user's fame profile contains
    # a negative fame value for any of the post's expertise areas
    if Fame.objects.filter(
            user=user,
            expertise_area_id__in=expertise_area_ids,
            fame_level__numeric_value__lt=0,
    ).exists():
        post.published = False

    # ------------------------------------------------------------------ #
    # T2 — Update fame levels for expertise areas with negative truth ratings
    # ------------------------------------------------------------------ #

    # For each expertise area of this post, check if a fame penalty applies.
    for expertise_area_entry in _expertise_areas:
        truth_rating = expertise_area_entry["truth_rating"]

        # Skip areas with no rating or a positive rating — no penalty applies.
        if truth_rating is None or truth_rating.numeric_value >= 0:
            continue

        expertise_area = expertise_area_entry["expertise_area"]

        # Look up the existing Fame entry for this user + expertise area.
        fame_entry = Fame.objects.filter(
            user=user,
            expertise_area=expertise_area,
        ).select_related("fame_level").first()

        if fame_entry is None:

            # ---------------------------------------------------------- #
            # T2b — No fame record yet: create one at the lowest entry level
            #        ("Confuser") to start the penalty track.
            # ---------------------------------------------------------- #

            confuser = FameLevels.objects.get(name="Confuser")
            Fame.objects.create(
                user=user,
                expertise_area=expertise_area,
                fame_level=confuser,
            )
        else:

            # ---------------------------------------------------------- #
            # T2a — Fame record exists: attempt to reduce by one level.
            # ---------------------------------------------------------- #

            old_level = fame_entry.fame_level
            try:
                # get_next_lower_fame_level() raises ValueError if the
                # current level is already the lowest possible.
                new_level = old_level.get_next_lower_fame_level()
                fame_entry.fame_level = new_level
                fame_entry.save(update_fields=["fame_level"])

                # ------------------------------------------------------ #
                #                       T4
                # If the new fame level falls below "Super Pro",
                # remove the user from this expertise area's community.
                # ------------------------------------------------------ #

                super_pro_level = FameLevels.objects.get(name="Super Pro")

                if new_level.numeric_value < super_pro_level.numeric_value:
                    # Remove user from this expertise area community
                    user.communities.remove(expertise_area)

            except ValueError:

                # -------------------------------------------------------- #
                # T2c — Already at the lowest fame level: ban the user.
                # -------------------------------------------------------- #

                # 1. Deactivate the account.
                user.is_active = False
                user.save(update_fields=["is_active"]) # writes the changes to the database

                # 2. Unpublish all posts by this user without deleting them.
                Posts.objects.filter(author=user).update(published=False)

                # ------------------------------------------------------ #
                # T4 — Remove the banned user from all communities.
                # ------------------------------------------------------ #

                # Remove user from all communities when banned
                user.communities.clear() # removes all relations

                redirect_to_logout = True

    post.save()

    return (
        {"published": post.published, "id": post.id},
        _expertise_areas,
        redirect_to_logout,
    )


def rate_post(
        user: SocialNetworkUsers, post: Posts, rating_type: str, rating_score: int
):
    """Rate a post. Assumes that the user is authenticated. If user already rated the post with the given rating_type,
    update that rating score."""
    user_rating = None
    try:
        user_rating = user.userratings_set.get(post=post, rating_type=rating_type)
    except user.userratings_set.model.DoesNotExist:
        pass

    if user == post.author:
        raise PermissionError(
            "User is the author of the post. You cannot rate your own post."
        )

    if user_rating is not None:
        # update the existing rating:
        user_rating.rating_score = rating_score
        user_rating.save()
        return {"rated": True, "type": "update"}
    else:
        # create a new rating:
        user.userratings_set.add(
            post,
            through_defaults={"rating_type": rating_type, "rating_score": rating_score},
        )
        user.save()
        return {"rated": True, "type": "new"}


def fame(user: SocialNetworkUsers):
    """Get the fame of a user. Assumes that the user is authenticated."""
    try:
        user = SocialNetworkUsers.objects.get(id=user.id)
    except SocialNetworkUsers.DoesNotExist:
        raise ValueError("User does not exist")

    return user, Fame.objects.filter(user=user)

# ---------------------------------------------------------------------------
# T3 — Community Timeline
# ---------------------------------------------------------------------------

def bullshitters():
    """Return a Python dictionary mapping each existing expertise area in the fame profiles to a list of the users
    having negative fame for that expertise area. Each list should contain Python dictionaries as entries with keys
    'user' (for the user) and 'fame_level_numeric' (for the corresponding fame value), and should be ranked, i.e.,
    users with the lowest fame are shown first, in case there is a tie, within that tie sort by date_joined
    (most recent first). Note that expertise areas with no bullshitters may be omitted.
    """

    # Fetch all Fame entries where the numeric level is strictly negative.
    # Order at the DB level so entries are already in the required sort order.
    negative_entries = (
        Fame.objects
        .filter(fame_level__numeric_value__lt=0)
        .select_related("fame_level", "user", "expertise_area")
        .order_by("fame_level__numeric_value", "-user__date_joined")
    )

    # Build the result dict by iterating the ordered queryset once.
    # setdefault ensures we only initialise the list the first time we see
    # a given expertise area.
    result = {}

    for entry in negative_entries:
        area = entry.expertise_area
        user_entry = {
            "user": entry.user,
            "fame_level_numeric": entry.fame_level.numeric_value,
        }
        result.setdefault(area, []).append(user_entry)

    return result


# ---------------------------------------------------------------------------
#  T4 - Community Join / Leave
# ---------------------------------------------------------------------------

def join_community(user: SocialNetworkUsers, community: ExpertiseAreas):
    """Join a specified community. Note that this method does not check whether the user is eligible for joining the
    community.
    """

    # Create a relationship between `user` and the given `community` (`ExpertiseArea`).
    user.communities.add(community)
    user.save()


def leave_community(user: SocialNetworkUsers, community: ExpertiseAreas):
    """Leave a specified community."""

    # Remove a relationship between `user` and the given `community` (`ExpertiseArea`).
    user.communities.remove(community)
    user.save()


# ---------------------------------------------------------------------------
# T5
# ---------------------------------------------------------------------------

from django.db.models import Q, Exists, OuterRef, When, IntegerField, FloatField, Count, ExpressionWrapper, Case, Value, F, Prefetch

from fame.models import Fame, FameLevels, FameUsers, ExpertiseAreas
from socialnetwork.models import Posts, SocialNetworkUsers


# general methods independent of html and REST views
# should be used by REST and html views


def _get_social_network_user(user) -> SocialNetworkUsers:
    """Given a FameUser, gets the social network user from the request. Assumes that the user is authenticated."""
    try:
        user = SocialNetworkUsers.objects.get(id=user.id)
    except SocialNetworkUsers.DoesNotExist:
        raise PermissionError("User does not exist")
    return user


# ---------------------------------------------------------------------------
# T4 — Community Timeline
# ---------------------------------------------------------------------------

def timeline(user: SocialNetworkUsers, start: int = 0, end: int = None, published=True, community_mode=False):
    """Get the timeline of the user. Assumes that the user is authenticated."""

    if community_mode:
        # T4
        # in community mode, posts of communities are displayed if ALL of the following criteria are met:
        # 1. the author of the post is a member of the community
        # 2. the user is a member of the community
        # 3. the post contains the community's expertise area
        # 4. the post is published or the user is the author

        # Communities des Users holen
        user_communities = user.communities.all()

        if community_mode:

            # ------------------------------------------------------------------ #
            # T4 — Community Timeline Filter
            # ------------------------------------------------------------------ #

            # First we define a sub-query (not yet executed).
            # For each post (referenced via OuterRef) in the outer query, check whether there EXISTS
            # an ExpertiseArea that satisfies ALL three conditions:
            #   1. The post is classified under this ExpertiseArea (classified_as = relation between ExpertiseAreas and Posts)
            #   2. The post's author is a member of this ExpertiseArea's community
            #   3. The currently logged-in user is also a member of this ExpertiseArea (pk = primary key must be in the user's community IDs)
            valid_shared_community = Exists(
                ExpertiseAreas.objects.filter(
                    classified_as=OuterRef('pk'),
                    socialnetworkusers=OuterRef('author'),
                    pk__in=user.communities.values('pk'),
                )
            )

            # Here we select posts with a valid shared community (using the previous sub-query) and check
            # whether the post is published or the author is the user.
            posts = Posts.objects.filter(
                valid_shared_community
            ).filter(
                Q(published=published) | Q(author=user) # Q = OR
            ).order_by("-submitted")
    else:
        # in standard mode, posts of followed users are displayed
        _follows = user.follows.all()
        posts = Posts.objects.filter(
            (Q(author__in=_follows) & Q(published=published)) | Q(author=user)
        ).order_by("-submitted")
    if end is None:
        return posts[start:]
    else:
        return posts[start:end + 1]


def search(keyword: str, start: int = 0, end: int = None, published=True):
    """Search for all posts in the system containing the keyword. Assumes that all posts are public"""
    posts = Posts.objects.filter(
        Q(content__icontains=keyword)
        | Q(author__email__icontains=keyword)
        | Q(author__first_name__icontains=keyword)
        | Q(author__last_name__icontains=keyword),
        published=published,
    ).order_by("-submitted")
    if end is None:
        return posts[start:]
    else:
        return posts[start:end + 1]


def follows(user: SocialNetworkUsers, start: int = 0, end: int = None):
    """Get the users followed by this user. Assumes that the user is authenticated."""
    _follows = user.follows.all()
    if end is None:
        return _follows[start:]
    else:
        return _follows[start:end + 1]


def followers(user: SocialNetworkUsers, start: int = 0, end: int = None):
    """Get the followers of this user. Assumes that the user is authenticated."""
    _followers = user.followed_by.all()
    if end is None:
        return _followers[start:]
    else:
        return _followers[start:end + 1]


def follow(user: SocialNetworkUsers, user_to_follow: SocialNetworkUsers):
    """Follow a user. Assumes that the user is authenticated. If user already follows the user, signal that."""
    if user_to_follow in user.follows.all():
        return {"followed": False}
    user.follows.add(user_to_follow)
    user.save()
    return {"followed": True}


def unfollow(user: SocialNetworkUsers, user_to_unfollow: SocialNetworkUsers):
    """Unfollow a user. Assumes that the user is authenticated. If user does not follow the user anyway, signal that."""
    if user_to_unfollow not in user.follows.all():
        return {"unfollowed": False}
    user.follows.remove(user_to_unfollow)
    user.save()
    return {"unfollowed": True}

# ---------------------------------------------------------------------------
# T1 / T2 / T4 — Post Submission
# ---------------------------------------------------------------------------

def submit_post(
        user: SocialNetworkUsers,
        content: str,
        cites: Posts = None,
        replies_to: Posts = None,
):
    """Submit a post for publication. Assumes that the user is authenticated.
    returns a tuple of three elements:
    1. a dictionary with the keys "published" and "id" (the id of the post)
    2. a list of dictionaries containing the expertise areas and their truth ratings
    3. a boolean indicating whether the user was banned and logged out and should be redirected to the login page
    """

    # create post  instance:
    post = Posts.objects.create(
        content=content,
        author=user,
        cites=cites,
        replies_to=replies_to,
    )

    # classify the content into expertise areas:
    # only publish the post if none of the expertise areas contains bullshit:
    _at_least_one_expertise_area_contains_bullshit, _expertise_areas = (
        post.determine_expertise_areas_and_truth_ratings()
    )
    post.published = not _at_least_one_expertise_area_contains_bullshit

    redirect_to_logout = False

    # ------------------------------------------------------------------ #
    #       T1 —  not publish posts that have an expertise area
    # which is contained in the user’s fame profile and marked negative there
    # ------------------------------------------------------------------ #

    # _expertise_areas_ contains additional data like truth rating
    # Only collect the IDs (primary key) of all expertise areas this post is assigned to.
    expertise_area_ids = [
        entry["expertise_area"].id
        for entry in _expertise_areas
    ]

    # Unpublish the post if the user's fame profile contains
    # a negative fame value for any of the post's expertise areas
    if Fame.objects.filter(
            user=user,
            expertise_area_id__in=expertise_area_ids,
            fame_level__numeric_value__lt=0,
    ).exists():
        post.published = False

    # ------------------------------------------------------------------ #
    # T2 — Update fame levels for expertise areas with negative truth ratings
    # ------------------------------------------------------------------ #

    # For each expertise area of this post, check if a fame penalty applies.
    for expertise_area_entry in _expertise_areas:
        truth_rating = expertise_area_entry["truth_rating"]

        # Skip areas with no rating or a positive rating — no penalty applies.
        if truth_rating is None or truth_rating.numeric_value >= 0:
            continue

        expertise_area = expertise_area_entry["expertise_area"]

        # Look up the existing Fame entry for this user + expertise area.
        fame_entry = Fame.objects.filter(
            user=user,
            expertise_area=expertise_area,
        ).select_related("fame_level").first()

        if fame_entry is None:

            # ---------------------------------------------------------- #
            # T2b — No fame record yet: create one at the lowest entry level
            #        ("Confuser") to start the penalty track.
            # ---------------------------------------------------------- #

            confuser = FameLevels.objects.get(name="Confuser")
            Fame.objects.create(
                user=user,
                expertise_area=expertise_area,
                fame_level=confuser,
            )
        else:

            # ---------------------------------------------------------- #
            # T2a — Fame record exists: attempt to reduce by one level.
            # ---------------------------------------------------------- #

            old_level = fame_entry.fame_level
            try:
                # get_next_lower_fame_level() raises ValueError if the
                # current level is already the lowest possible.
                new_level = old_level.get_next_lower_fame_level()
                fame_entry.fame_level = new_level
                fame_entry.save(update_fields=["fame_level"])

                # ------------------------------------------------------ #
                #                       T4
                # If the new fame level falls below "Super Pro",
                # remove the user from this expertise area's community.
                # ------------------------------------------------------ #

                super_pro_level = FameLevels.objects.get(name="Super Pro")

                if new_level.numeric_value < super_pro_level.numeric_value:
                    # Remove user from this expertise area community
                    user.communities.remove(expertise_area)

            except ValueError:

                # -------------------------------------------------------- #
                # T2c — Already at the lowest fame level: ban the user.
                # -------------------------------------------------------- #

                # 1. Deactivate the account.
                user.is_active = False
                user.save(update_fields=["is_active"]) # writes the changes to the database

                # 2. Unpublish all posts by this user without deleting them.
                Posts.objects.filter(author=user).update(published=False)

                # ------------------------------------------------------ #
                # T4 — Remove the banned user from all communities.
                # ------------------------------------------------------ #

                # Remove user from all communities when banned
                user.communities.clear() # removes all relations

                redirect_to_logout = True

    post.save()

    return (
        {"published": post.published, "id": post.id},
        _expertise_areas,
        redirect_to_logout,
    )


def rate_post(
        user: SocialNetworkUsers, post: Posts, rating_type: str, rating_score: int
):
    """Rate a post. Assumes that the user is authenticated. If user already rated the post with the given rating_type,
    update that rating score."""
    user_rating = None
    try:
        user_rating = user.userratings_set.get(post=post, rating_type=rating_type)
    except user.userratings_set.model.DoesNotExist:
        pass

    if user == post.author:
        raise PermissionError(
            "User is the author of the post. You cannot rate your own post."
        )

    if user_rating is not None:
        # update the existing rating:
        user_rating.rating_score = rating_score
        user_rating.save()
        return {"rated": True, "type": "update"}
    else:
        # create a new rating:
        user.userratings_set.add(
            post,
            through_defaults={"rating_type": rating_type, "rating_score": rating_score},
        )
        user.save()
        return {"rated": True, "type": "new"}


def fame(user: SocialNetworkUsers):
    """Get the fame of a user. Assumes that the user is authenticated."""
    try:
        user = SocialNetworkUsers.objects.get(id=user.id)
    except SocialNetworkUsers.DoesNotExist:
        raise ValueError("User does not exist")

    return user, Fame.objects.filter(user=user)

# ---------------------------------------------------------------------------
# T3 — Community Timeline
# ---------------------------------------------------------------------------

def bullshitters():
    """Return a Python dictionary mapping each existing expertise area in the fame profiles to a list of the users
    having negative fame for that expertise area. Each list should contain Python dictionaries as entries with keys
    'user' (for the user) and 'fame_level_numeric' (for the corresponding fame value), and should be ranked, i.e.,
    users with the lowest fame are shown first, in case there is a tie, within that tie sort by date_joined
    (most recent first). Note that expertise areas with no bullshitters may be omitted.
    """

    # Fetch all Fame entries where the numeric level is strictly negative.
    # Order at the DB level so entries are already in the required sort order.
    negative_entries = (
        Fame.objects
        .filter(fame_level__numeric_value__lt=0)
        .select_related("fame_level", "user", "expertise_area")
        .order_by("fame_level__numeric_value", "-user__date_joined")
    )

    # Build the result dict by iterating the ordered queryset once.
    # setdefault ensures we only initialise the list the first time we see
    # a given expertise area.
    result = {}

    for entry in negative_entries:
        area = entry.expertise_area
        user_entry = {
            "user": entry.user,
            "fame_level_numeric": entry.fame_level.numeric_value,
        }
        result.setdefault(area, []).append(user_entry)

    return result


# ---------------------------------------------------------------------------
#  T4 - Community Join / Leave
# ---------------------------------------------------------------------------

def join_community(user: SocialNetworkUsers, community: ExpertiseAreas):
    """Join a specified community. Note that this method does not check whether the user is eligible for joining the
    community.
    """

    # Create a relationship between `user` and the given `community` (`ExpertiseArea`).
    user.communities.add(community)
    user.save()


def leave_community(user: SocialNetworkUsers, community: ExpertiseAreas):
    """Leave a specified community."""

    # Remove a relationship between `user` and the given `community` (`ExpertiseArea`).
    user.communities.remove(community)
    user.save()


# ---------------------------------------------------------------------------
# T5
# ---------------------------------------------------------------------------

def similar_users(user: SocialNetworkUsers):
    """Compute the similarity of user with all other users. The method returns a QuerySet of FameUsers annotated
    with an additional field 'similarity'. Sort the result in descending order according to 'similarity', in case
    there is a tie, within that tie sort by date_joined (most recent first)"""

    # Create a dictionary mapping each expertise area ID to the user's fame level.
    own_fame = {
        entry.expertise_area_id: entry.fame_level.numeric_value
        for entry in Fame.objects.filter(user=user).select_related("fame_level")
    }

    # If the user has no fame entries, return an empty queryset with a default
    # similarity annotation so the returned queryset has the same structure.
    if not own_fame:
        return SocialNetworkUsers.objects.none().annotate(
            similarity=Value(0.0, output_field=FloatField())
        )

    # Compare the current user's fame levels with those of other users.
    # Count the number of shared expertise areas where the fame difference is at most 100.
    other_fame = {}
    # Get other users' fame entries for expertise areas shared with the current user.
    for entry in Fame.objects.exclude(user=user).filter(
            expertise_area_id__in=own_fame.keys()
    ).select_related("fame_level"):
        # Count how many shared expertise areas have a fame level difference of at most 100 for each user.
        if abs(own_fame[entry.expertise_area_id] - entry.fame_level.numeric_value) <= 100:
            other_fame[entry.user_id] = other_fame.get(entry.user_id, 0) + 1

    # Calculate the similarity score for each user as:
    # matching expertise areas / total expertise areas of the current user.
    denominator = float(len(own_fame))
    similarities = {
        user_id: matching_areas / denominator
        for user_id, matching_areas in other_fame.items()
        if matching_areas > 0
    }
    # If no similar users were found, return an empty queryset with a default
    # similarity annotation so the returned queryset has the same structure.
    if not similarities:
        return SocialNetworkUsers.objects.none().annotate(
            similarity=Value(0.0, output_field=FloatField())
        )
    # Assign a similarity score to each user based on precomputed values,
    # using a SQL CASE expression with a default value of 0.0.
    similarity_case = Case(
        *[
            When(pk=user_id, then=Value(score))
            for user_id, score in similarities.items()
        ],
        default=Value(0.0),
        output_field=FloatField(),
    )

    # Execute the query
    # Fetch users matching the similarity map, add similarity score,
    # and order by similarity and join date.
    return SocialNetworkUsers.objects.filter(pk__in=similarities.keys()).annotate(
        similarity=similarity_case
    ).order_by("-similarity", "-date_joined")