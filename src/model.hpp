#pragma once
// SIPP-IP baseline. Motion primitives adapted from PathPlanning/SIPP-IP (MIT).
// See vendor/sipp-ip/LICENSE and docs/model.md for provenance and semantics.
#include <algorithm>
#include <array>
#include <chrono>
#include <iostream>
#include <memory>
#include <queue>
#include <stdexcept>
#include <string>
#include <tuple>
#include <vector>
using Clock = std::chrono::steady_clock;
using Interval = std::pair<int, int>;
using Intervals = std::vector<Interval>;
struct Touch { int dr, dc, first, last; };
struct Primitive { std::string name; int orientation, velocity, duration, dr, dc; std::vector<Touch> touches; };
using Actions = std::array<std::array<std::vector<Primitive>, 2>, 4>;

Actions actions() {
    Actions result;
    const int dr[] = {0,-1,0,1}, dc[] = {1,0,-1,0};
    const int first[] = {0,0,20,28,34}, span[] = {20,29,15,12,6};
    for (int o=0; o<4; ++o) {
        for (int turn : {1,3})
            result[o][0].push_back({turn==1?"left":"right",(o+turn)%4,0,20,0,0,{{0,0,0,20}}});
        Primitive accel{"accelerate",o,1,40,4*dr[o],4*dc[o],{}};
        Primitive brake{"brake",o,0,40,4*dr[o],4*dc[o],{}};
        for(int j=0;j<5;++j) {
            accel.touches.push_back({j*dr[o],j*dc[o],first[j],first[j]+span[j]});
            int k=4-j, f=40-first[k]-span[k];
            brake.touches.push_back({j*dr[o],j*dc[o],f,f+span[k]});
        }
        result[o][0].push_back(accel);
        result[o][1].push_back(brake);
        result[o][1].push_back({"cruise",o,1,5,dr[o],dc[o],{{0,0,0,5},{dr[o],dc[o],0,5}}});
    }
    return result;
}
Intervals normalize(Intervals xs) {
    std::sort(xs.begin(),xs.end()); Intervals out;
    for(auto [a,b]:xs) {
        if(a>b) continue;
        if(out.empty() || a>out.back().second+1) out.push_back({a,b});
        else out.back().second=std::max(out.back().second,b);
    }
    return out;
}
Intervals subtract(const Intervals& xs, const Intervals& blocks) {
    Intervals out;
    for(auto [a,b]:xs) {
        for(auto [l,u]:blocks) {
            if(u<a) continue;
            if(l>b) break;
            if(l>a) out.push_back({a,l-1});
            a=std::max(a,u+1); if(a>b) break;
        }
        if(a<=b) out.push_back({a,b});
    }
    return out;
}
struct Node { int r,c,o,v,lo,hi,parent,action,dep_lo,dep_hi; };
struct Step { std::string action; int r,c,o,v,begin,end,nr,nc,no,nv; };
struct Stats { long long expansions=0, generated=0, projections=0, pops=0, peak_open=0; };
