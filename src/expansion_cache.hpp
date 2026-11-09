#pragma once
#include "model.hpp"

// Each ordinary expansion emits a contiguous range of child nodes, including
// an empty range when all outgoing actions fail. Only the last search is kept.
struct ExpansionCache {
    struct Record { int lo,hi,first,last,next; };
    std::vector<int> heads;
    std::vector<Record> records;
#ifdef SIPP_COMPACT_CACHE
    struct Child { int action,dep_lo,dep_hi,wait_end; };
    std::vector<Child> children;

    void retain_children(std::vector<Node>& nodes) {
        size_t count=0;
        for(const auto& r:records) count+=r.last-r.first;
        children.reserve(count);
        for(auto& r:records) {
            int begin=static_cast<int>(children.size());
            for(int i=r.first;i<r.last;++i) {
                const auto& n=nodes[i];
                children.push_back({n.action,n.dep_lo,n.dep_hi,n.hi});
            }
            r.first=begin;
            r.last=static_cast<int>(children.size());
        }
    }
#else
    std::vector<Node> children;
    void retain_children(std::vector<Node>& nodes) { children=std::move(nodes); }
#endif

    void record(int key,int lo,int hi,int first,int last) {
        int id=static_cast<int>(records.size());
        records.push_back({lo,hi,first,last,heads[key]});
        heads[key]=id;
    }
    const Record* containing(int key,int lo,int hi) const {
        for(int i=heads[key];i>=0;i=records[i].next) {
            const auto& r=records[i];
            if(r.lo<=lo && hi<=r.hi) return &r;
        }
        return nullptr;
    }
};
