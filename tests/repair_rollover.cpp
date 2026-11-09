// Reach the state after 2^64-1 unchanged forecasts without replaying them.
#define main sipp_repair_protocol_main
#include "../src/incremental.cpp"
#undef main

int main(){
    int h,w;Input first,second;
    if(!(std::cin>>h>>w)||!read_input(first,h,w))return 2;
    Incremental planner(std::move(first));planner.search();planner.verify_invariants();
    planner.epoch=std::numeric_limits<unsigned long long>::max();
    if(!(std::cin>>h>>w)||!read_input(second,h,w))return 2;
    planner.update(std::move(second));planner.verify_invariants();
    auto result=planner.search();planner.verify_invariants();
    if(planner.epoch!=1||result.second<0)return 3;
    bool guarded=false;
    try{Incremental::storage_id(static_cast<size_t>(std::numeric_limits<int>::max()));}
    catch(const std::length_error&){guarded=true;}
    if(!guarded)return 4;
    std::cout<<result.first<<' '<<planner.labels[result.second].n.lo<<'\n';
}
