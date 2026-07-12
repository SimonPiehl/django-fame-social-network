from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect
from django.urls import reverse
from django.views.decorators.http import require_http_methods

from socialnetwork import api
from socialnetwork.api import _get_social_network_user
from socialnetwork.models import SocialNetworkUsers
from fame.models import ExpertiseAreas, Fame  # T7
from socialnetwork.serializers import PostsSerializer


@require_http_methods(["GET"])
@login_required
# 'request' is the HTTP request sent by the client, containing information about the current request.
def timeline(request):
    # T7: Initialize community mode to False on first visit
    # Set the default community mode to False if it is not already stored in the session.
    if 'community_mode' not in request.session:
        request.session['community_mode'] = False

    keyword = request.GET.get("search", "")
    published = request.GET.get("published", True)
    error = request.GET.get("error", None)

    user = _get_social_network_user(request.user)

    # T7: Load communities the user has already joined
    joined_communities = user.communities.all()

    # T7: Load communities the user is allowed to join (Super Pro = numeric_value >= 100)
    # but has not yet joined
    eligible_area_ids = Fame.objects.filter(
        user=user,
        fame_level__numeric_value__gte=100,
    ).values('expertise_area_id')

    eligible_communities = ExpertiseAreas.objects.filter(
        id__in=eligible_area_ids
    ).exclude(
        id__in=joined_communities.values('id')
    )

    # If a search keyword is provided, return search results.
    # Otherwise, return the normal timeline feed.
    # In both cases, build a context dictionary for the template.
    if keyword and keyword != "":
        # Context dictionary containing the data passed from the view to the HTML template.
        context = {
            # gives the posts containing only the keyword
            "posts": PostsSerializer(
                api.search(keyword, published=published), many=True
            ).data,
            "searchkeyword": keyword,
            "error": error,
            "followers": list(api.follows(user).values_list('id', flat=True)),
            "community_mode": request.session.get('community_mode', False), # T7
            "joined_communities": joined_communities, # T7
            "eligible_communities": eligible_communities, # T7
        }
    else:
        context = {
            "posts": PostsSerializer(
                api.timeline(
                    user,
                    published=published,
                    community_mode=request.session.get('community_mode', False), # T7
                ),
                many=True,
            ).data,
            "searchkeyword": "",
            "error": error,
            "followers": list(api.follows(user).values_list('id', flat=True)),
            "community_mode": request.session.get('community_mode', False), # T7
            "joined_communities": joined_communities, # T7
            "eligible_communities": eligible_communities, # T7
        }

    return render(request, "timeline.html", context=context)


@require_http_methods(["POST"])
@login_required
def follow(request):
    user = _get_social_network_user(request.user)
    user_to_follow = SocialNetworkUsers.objects.get(id=request.POST.get("user_id"))
    api.follow(user, user_to_follow)
    return redirect(reverse("sn:timeline"))


@require_http_methods(["POST"])
@login_required
def unfollow(request):
    user = _get_social_network_user(request.user)
    user_to_unfollow = SocialNetworkUsers.objects.get(id=request.POST.get("user_id"))
    api.unfollow(user, user_to_unfollow)
    return redirect(reverse("sn:timeline"))


@require_http_methods(["GET"])
@login_required
# T6: View for the bullshitters page
def bullshitters(request):
    raw = api.bullshitters()
    # Convert dictionary into a list of objects because templates
    # work better with iterable structures than raw dicts.
    context = {
        "bullshitters": [
            {"area": area, "users": users}
            for area, users in raw.items()
        ],
    }
    # Render combines the template with the provided context data
    # and returns a complete HTTP response
    return render(request, "bullshitters.html", context=context)

@require_http_methods(["POST"])
@login_required
# T7: Toggles the user's community mode on or off.
def toggle_community_mode(request):
    # Invert the current community mode stored in the session.
    request.session['community_mode'] = not request.session.get('community_mode', False) # return False as the default value.
    return redirect(reverse("sn:timeline")) # reverse() finds URL path

@require_http_methods(["POST"])
@login_required
# T7: Adds the logged-in user to a community.
def join_community(request):
    user = _get_social_network_user(request.user)
    community_id = request.POST.get("community_id")
    community = ExpertiseAreas.objects.get(id=community_id)
    api.join_community(user, community)
    return redirect(reverse("sn:timeline"))

@require_http_methods(["POST"])
@login_required
# T7: Removes the logged-in user from a community.
# This view only accepts POST requests because it modifies the server state
def leave_community(request):
    user = _get_social_network_user(request.user)
    community_id = request.POST.get("community_id")
    community = ExpertiseAreas.objects.get(id=community_id)
    api.leave_community(user, community)
    # Redirect the user back to the timeline after leaving the community.
    return redirect(reverse("sn:timeline"))

@require_http_methods(["GET"])
@login_required
# T8: View for the similar users page
def similar_users(request):
    user = _get_social_network_user(request.user)
    # Calls api.similar_users() and passes the annotated QuerySet of similar users to the template.
    context = {
        "similar_users": api.similar_users(user),
    }
    return render(request, "similar_users.html", context=context)